import io
import time
from dataclasses import replace

import pytest
from fastapi import HTTPException
from PIL import Image
from starlette.requests import Request

from backend import content_review, database


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "wiki.db"
    monkeypatch.setattr(database, "get_database_path", lambda: path)
    monkeypatch.setattr(content_review, "get_database_path", lambda: path)
    monkeypatch.setattr(
        database, "settings", replace(database.settings, database_backend="sqlite")
    )
    monkeypatch.setattr(content_review, "get_media_storage", lambda: None)
    with database.get_db_connection() as db:
        db._connection.execute(
            "INSERT INTO users(id,username,password_hash,role) VALUES(1,'member','','user'),(2,'admin','','admin')"
        )
    return content_review.site, {"id": 1, "role": "user", "emailVerified": True}


def verdict(job, decision="allow"):
    return {
        "jobId": job["jobId"],
        "decision": decision,
        "categories": [] if decision == "allow" else ["uncertain"],
        "evidence": [] if decision == "allow" else ["需要人工确认"],
        "explanation": "内容正常" if decision == "allow" else "需要人工确认",
    }


def test_profile_is_private_until_approved_and_late_result_cannot_restore(store):
    site, user = store
    content_review.submit("profile", 1, user, "待审核简介")
    with site.db() as db:
        assert db.execute("SELECT bio FROM users WHERE id=1").fetchone()[0] == ""
    job = site.claim(1, 60)
    assert site.complete(job, verdict(job))
    with site.db() as db:
        assert (
            db.execute("SELECT bio FROM users WHERE id=1").fetchone()[0] == "待审核简介"
        )
    second = content_review.submit("profile", 1, user, "撤回的简介")["data"]["id"]
    late_job = site.claim(1, 60)
    content_review.withdraw(second, user)
    assert not site.complete(late_job, verdict(late_job))
    with site.db() as db:
        assert (
            db.execute(
                "SELECT status FROM _private_content_submissions WHERE id=?", (second,)
            ).fetchone()[0]
            == "withdrawn"
        )
        assert (
            db.execute("SELECT bio FROM users WHERE id=1").fetchone()[0] == "待审核简介"
        )


def test_image_order_and_private_access_survive_review(store):
    site, user = store
    with site.db(True) as db:
        db.execute(
            "INSERT INTO projects(id,name,leader,members,category,year,description) VALUES(1,'project','','[]','category',2026,'')"
        )
        db.execute(
            "INSERT INTO people(id,display_name,user_id,status) VALUES(1,'member',1,'claimed')"
        )
        db.execute(
            "INSERT INTO project_members(project_id,person_id,role,display_name_snapshot,sort_order) VALUES(1,1,'member','member',0)"
        )
    raw = io.BytesIO()
    Image.new("RGB", (4, 4), "blue").save(raw, "PNG")
    images = [content_review.store_private_image(raw.getvalue()) for _ in range(2)]
    images.sort(key=lambda m: m["id"], reverse=True)
    ident = content_review.submit("update", 1, user, "图文动态", {}, images)["data"][
        "id"
    ]
    request = Request({"type": "http", "headers": []})
    with pytest.raises(HTTPException) as error:
        content_review.private_media(images[0]["id"], request)
    assert error.value.status_code == 404
    job = site.claim(1, 60)
    assert job["imageIds"] == [m["id"] for m in images]
    assert len(job["images"]) == 2
    assert site.complete(job, verdict(job, "review"))
    with site.db() as db:
        assert db.execute("SELECT COUNT(*) FROM project_updates").fetchone()[0] == 0
    content_review.decide(
        ident, {"action": "approve", "note": "人工核验通过"}, {"id": 2}
    )
    assert content_review.private_media(images[0]["id"], request).status_code == 200


def test_muted_or_unverified_user_cannot_submit(store):
    site, user = store
    with pytest.raises(HTTPException):
        content_review.submit("profile", 1, {**user, "emailVerified": False}, "blocked")
    with site.db(True) as db:
        db.execute(
            "UPDATE users SET is_muted=1,muted_until=? WHERE id=1",
            (int(time.time()) + 3600,),
        )
    with pytest.raises(HTTPException):
        content_review.submit("profile", 1, user, "blocked")
    with site.db() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM _private_content_submissions").fetchone()[
                0
            ]
            == 0
        )


@pytest.mark.parametrize("active", [True, False])
def test_json_result_checks_central_author_status_before_publication(
    store, monkeypatch, active
):
    import json

    site, user = store
    content_review.submit("profile", 1, user, "审核中的简介")
    job = site.claim(1, 60)
    monkeypatch.setattr(
        "nethub_status.read_account_status",
        lambda *args: {"active": active, "emailVerified": True},
    )
    assert site.complete(job, json.dumps(verdict(job)))
    with site.db() as db:
        assert db.execute("SELECT bio FROM users WHERE id=1").fetchone()[0] == (
            "审核中的简介" if active else ""
        )
        assert db.execute("SELECT status FROM _private_content_submissions").fetchone()[
            0
        ] == ("published" if active else "review")


def test_cleanup_retains_media_on_storage_failure_and_redacts_only_old_terminal_records(
    store, monkeypatch
):
    from scripts import cleanup_governance

    site, user = store
    ident = content_review.submit("profile", 1, user, "旧提交内容")["data"]["id"]
    pending = content_review.submit("profile", 1, user, "仍在审核中")["data"]["id"]
    media_id = "b" * 32
    with site.db(True) as db:
        db.execute(
            "UPDATE _private_content_submissions SET status='rejected',updated_at=datetime('now','-181 days') WHERE id=?",
            (ident,),
        )
        db.execute(
            "UPDATE _moderation_content_jobs SET state='cancelled',result_json='old',updated_at=datetime('now','-181 days') WHERE submission_id=?",
            (ident,),
        )
        db.execute(
            "INSERT INTO _private_content_media(id,submission_id,storage_key,sha256,mime) VALUES(?,?,?,'hash','image/jpeg')",
            (media_id, ident, "review-media/" + media_id + ".jpg"),
        )

    def failed(_key):
        raise OSError("injected storage outage")

    monkeypatch.setattr(cleanup_governance, "delete_private_image", failed)
    assert cleanup_governance.cleanup() == {"mediaDeleted": 0, "mediaFailed": 1}
    with site.db() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM _private_content_media").fetchone()[0] == 1
        )
        assert (
            db.execute(
                "SELECT content FROM _private_content_submissions WHERE id=?", (ident,)
            ).fetchone()[0]
            == ""
        )
        assert (
            db.execute(
                "SELECT content FROM _private_content_submissions WHERE id=?",
                (pending,),
            ).fetchone()[0]
            == "仍在审核中"
        )
    monkeypatch.setattr(cleanup_governance, "delete_private_image", lambda key: None)
    assert cleanup_governance.cleanup() == {"mediaDeleted": 1, "mediaFailed": 0}
    with site.db() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM _private_content_media").fetchone()[0] == 0
        )


@pytest.mark.parametrize("inactive", [False, True])
def test_cookie_session_central_ban_or_outage_blocks_profile(
    store, monkeypatch, inactive
):
    from fastapi.testclient import TestClient

    from backend.auth import SESSION_COOKIE_NAME, create_session
    from backend.main import app
    from nethub_status import AccountStatusUnavailable

    site, _user = store
    token = create_session(1)
    browser = TestClient(app)
    browser.cookies.set(SESSION_COOKIE_NAME, token)

    def status(*args):
        if inactive:
            return {"active": False, "emailVerified": True}
        raise AccountStatusUnavailable("injected outage")

    monkeypatch.setattr("nethub_status.read_account_status", status)
    response = browser.get("/api/auth/me")
    assert response.status_code == (403 if inactive else 503)
    with site.db() as db:
        session = db.execute(
            "SELECT revoked_at FROM auth_sessions WHERE user_id=1"
        ).fetchone()
        assert (session is None or session[0] is not None) == inactive
