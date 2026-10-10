"""Private submissions and leased AI review for project updates and profile bios."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import secrets
import time
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError

from backend.auth import get_current_user, get_optional_current_user
from backend.config import get_database_path
from backend.database import get_db_connection
from backend.media_storage import MediaStorageError, R2MediaStorage, get_media_storage
from nethub_moderation.policy import fingerprint, validate_result
from nethub_moderation.site import Site

router = APIRouter(prefix="/api", tags=["content governance"])


def require_speaker(user):
    if not user.get("emailVerified"):
        raise HTTPException(403, "请先在账号中心验证邮箱")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT is_muted,muted_until FROM users WHERE id=%s", (user["id"],)
            )
            row = cursor.fetchone()
    if (
        row
        and row["is_muted"]
        and (row["muted_until"] is None or row["muted_until"] > time.time())
    ):
        raise HTTPException(
            403, "账号已被本站禁言，请查看个人中心的原因、期限及申诉说明"
        )
    return user


def assert_unmuted(conn, user_id):
    row = conn.execute(
        "SELECT is_active,is_muted,muted_until FROM users WHERE id=?", (user_id,)
    ).fetchone()
    if (
        not row
        or not row["is_active"]
        or (
            row["is_muted"]
            and (row["muted_until"] is None or row["muted_until"] > time.time())
        )
    ):
        raise HTTPException(403, "账号不可发言")


def connect():
    facade = get_db_connection()
    if facade._connection is None:
        raise RuntimeError("内容预审需要 SQLite 主库")
    return facade._connection


def media_root():
    root = get_database_path().resolve().parent / "review-media"
    root.mkdir(parents=True, exist_ok=True)
    return root


def store_private_image(raw):
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(413, "单张图片不能超过 5MB")
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.width * source.height > 16_000_000:
                raise HTTPException(422, "图片不能超过 1600 万像素")
            if (
                source.format not in {"JPEG", "PNG", "WEBP"}
                or getattr(source, "n_frames", 1) != 1
            ):
                raise HTTPException(422, "仅支持静态 JPEG、PNG、WebP 图片")
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((2048, 2048))
            output = io.BytesIO()
            image.save(output, "JPEG", quality=90)
            payload = output.getvalue()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
    ) as exc:
        raise HTTPException(422, "图片无效或尺寸过大") from exc
    ident = secrets.token_hex(16)
    key = "review-media/" + ident + ".jpg"
    storage = get_media_storage()
    if isinstance(storage, R2MediaStorage):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "image.jpg"
            path.write_bytes(payload)
            storage.put_key_file(key, path, content_type="image/jpeg")
    else:
        (media_root() / (ident + ".jpg")).write_bytes(payload)
    return {
        "id": ident,
        "key": key,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "mime": "image/jpeg",
    }


def delete_private_image(key):
    if not re.fullmatch(r"review-media/[a-f0-9]{32}\.jpg", key):
        raise ValueError("私有媒体路径无效")
    storage = get_media_storage()
    if isinstance(storage, R2MediaStorage):
        storage.delete_key(key)
    else:
        (media_root() / key.removeprefix("review-media/")).unlink(missing_ok=True)


def read_private_image(row):
    key = row["storage_key"]
    if not re.fullmatch(r"review-media/[a-f0-9]{32}\.jpg", key):
        raise ValueError("私有媒体路径无效")
    storage = get_media_storage()
    if isinstance(storage, R2MediaStorage):
        with requests.get(
            storage.download_key_url(key),
            timeout=15,
            stream=True,
            allow_redirects=False,
        ) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 5 * 1024 * 1024:
                    raise ValueError("媒体对象过大")
                chunks.append(chunk)
            raw = b"".join(chunks)
    else:
        raw = (media_root() / key.removeprefix("review-media/")).read_bytes()
    if hashlib.sha256(raw).hexdigest() != row["sha256"]:
        raise ValueError("媒体内容摘要不匹配")
    return raw


def submission_hash(content, media):
    return fingerprint(
        json.dumps(
            [content, [(m["id"], m["sha256"]) for m in media]], ensure_ascii=False
        )
    )


def submit(
    kind, target_id, user, content, metadata=None, media=None, *, connection=None
):
    require_speaker(user)
    media = media or []
    ident = secrets.token_hex(16)
    with site.db(True) if connection is None else nullcontext(connection) as conn:
        assert_unmuted(conn, user["id"])
        if (
            kind == "update"
            and not conn.execute(
                "SELECT 1 FROM projects WHERE id=?", (target_id,)
            ).fetchone()
        ):
            raise HTTPException(404, "项目不存在")
        if kind == "update" and user["role"] != "admin":
            member = conn.execute(
                "SELECT 1 FROM project_members pm JOIN people p ON p.id=pm.person_id "
                "WHERE pm.project_id=? AND p.user_id=? AND p.status<>'archived'",
                (target_id, user["id"]),
            ).fetchone()
            if not member:
                raise HTTPException(403, "项目成员资格已变更，请刷新页面")
        if kind == "profile":
            pending = conn.execute(
                "SELECT id FROM _private_content_submissions WHERE kind='profile' AND user_id=? AND status IN ('pending','review')",
                (user["id"],),
            ).fetchall()
            for row in pending:
                conn.execute(
                    "UPDATE _private_content_submissions SET status='withdrawn',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (row["id"],),
                )
                conn.execute(
                    "UPDATE _moderation_content_jobs SET state='cancelled',token='' WHERE submission_id=?",
                    (row["id"],),
                )
        recent = conn.execute(
            "SELECT COUNT(*) AS recent FROM _private_content_submissions WHERE user_id=? AND created_at>=datetime('now','-1 minute')",
            (user["id"],),
        ).fetchone()["recent"]
        if recent >= 8:
            raise HTTPException(429, "提交过于频繁，请稍后重试")
        conn.execute(
            "INSERT INTO _private_content_submissions(id,kind,target_id,user_id,content,media_ids,metadata) VALUES(?,?,?,?,?,?,?)",
            (
                ident,
                kind,
                target_id,
                user["id"],
                content,
                json.dumps([m["id"] for m in media]),
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        for image in media:
            conn.execute(
                "INSERT INTO _private_content_media(id,submission_id,storage_key,sha256,mime) VALUES(?,?,?,?,?)",
                (image["id"], ident, image["key"], image["sha256"], image["mime"]),
            )
        conn.execute(
            "INSERT INTO _moderation_content_jobs(submission_id,content_hash) VALUES(?,?)",
            (ident, submission_hash(content, media)),
        )
    return {"data": {"id": ident, "moderationStatus": "pending"}}


def publish(conn, row, operator=None):
    if row["kind"] == "profile":
        conn.execute(
            "UPDATE users SET bio=? WHERE id=?", (row["content"], row["user_id"])
        )
    else:
        if not conn.execute(
            "SELECT 1 FROM projects WHERE id=?", (row["target_id"],)
        ).fetchone():
            raise ValueError("项目已删除")
        metadata = json.loads(row["metadata"])
        images = ["/api/content-media/" + mid for mid in json.loads(row["media_ids"])]
        position = conn.execute(
            "SELECT COALESCE(MIN(sort_order),0)-1 AS position FROM project_updates WHERE project_id=?",
            (row["target_id"],),
        ).fetchone()["position"]
        conn.execute(
            "INSERT INTO project_updates(id,project_id,content,images,metadata,sort_order,created_at,operator_id) VALUES(?,?,?,?,?,?,?,?)",
            (
                f"{row['target_id']}:{row['id']}",
                row["target_id"],
                row["content"],
                json.dumps(images),
                json.dumps({**metadata, "publicId": row["id"]}),
                position,
                datetime.now(UTC).isoformat(),
                operator,
            ),
        )
        conn.execute(
            "UPDATE projects SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (row["target_id"],),
        )
    conn.execute(
        "UPDATE _private_content_submissions SET status='published',decided_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (operator, row["id"]),
    )


class ReviewSite(Site):
    def claim(self, version, timeout):
        # Alternate queues so a steady stream of submissions cannot starve comments.
        self._prefer_comments = not getattr(self, "_prefer_comments", False)
        if self._prefer_comments:
            comment = super().claim(version, timeout)
            if comment:
                return comment
        claimed = None
        with self.db(True) as conn:
            now = time.time()
            conn.execute(
                "UPDATE _moderation_content_jobs SET state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'queued' END,token='',error_code='worker_interrupted' WHERE state='running' AND lease_until<?",
                (now,),
            )
            job = conn.execute(
                "SELECT j.*,s.content,s.status,s.media_ids FROM _moderation_content_jobs j JOIN _private_content_submissions s ON s.id=j.submission_id WHERE j.state='queued' AND j.ready_at<=? ORDER BY j.id LIMIT 1",
                (now,),
            ).fetchone()
            if job:
                media_by_id = {
                    m["id"]: dict(m)
                    for m in conn.execute(
                        "SELECT * FROM _private_content_media WHERE submission_id=?",
                        (job["submission_id"],),
                    )
                }
                order = json.loads(job["media_ids"])
                valid_media = len(order) == len(set(order)) and set(order) == set(
                    media_by_id
                )
                media = [media_by_id[mid] for mid in order] if valid_media else []
                if (
                    job["status"] != "pending"
                    or not valid_media
                    or submission_hash(job["content"], media) != job["content_hash"]
                ):
                    conn.execute(
                        "UPDATE _moderation_content_jobs SET state='cancelled',token='' WHERE id=?",
                        (job["id"],),
                    )
                else:
                    token = secrets.token_hex(24)
                    conn.execute(
                        "UPDATE _moderation_content_jobs SET state='running',attempts=attempts+1,token=?,lease_until=?,config_version=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (
                            token,
                            now + timeout + 60 + 20 * len(media),
                            version,
                            job["id"],
                        ),
                    )
                    data = {
                        "id": job["id"],
                        "submissionId": job["submission_id"],
                        "jobId": f"wiki:content:{job['id']}:{token}",
                        "token": token,
                        "currentComment": job["content"],
                        "parentComment": "",
                        "pageTitle": "成员投稿或个人简介",
                        "imageIds": [m["id"] for m in media],
                    }
                    # Images are fetched after the transaction below.
                    claimed = (data, media)
        if claimed is not None:
            data, media = claimed
            try:
                data["images"] = [
                    "data:"
                    + m["mime"]
                    + ";base64,"
                    + base64.b64encode(read_private_image(m)).decode()
                    for m in media
                ]
            except (requests.RequestException, MediaStorageError, OSError, ValueError):
                self.complete(data, error="media_read_failed")
                return None
            return data
        return super().claim(version, timeout) if not self._prefer_comments else None

    def complete(self, job, result=None, error="", retry_at=None):
        if result is not None:
            result = validate_result(result, job)
        if result is not None and result.get("decision") == "allow":
            # Central status is checked before acquiring the writer lock.
            from backend.config import settings
            from nethub_status import AccountStatusUnavailable, read_account_status

            with self.db() as conn:
                if "submissionId" in job:
                    author = conn.execute(
                        "SELECT u.* FROM users u JOIN _private_content_submissions s ON s.user_id=u.id WHERE s.id=?",
                        (job["submissionId"],),
                    ).fetchone()
                else:
                    author = conn.execute(
                        "SELECT u.* FROM users u JOIN comments c ON c.user_id=u.id WHERE c.id=?",
                        (job["commentId"],),
                    ).fetchone()
            permitted = False
            if author is not None:
                try:
                    status = read_account_status(
                        settings.oidc_issuer,
                        settings.oidc_client_id,
                        settings.oidc_client_secret,
                        author["auth_sub"],
                    )
                    permitted = (
                        status["active"]
                        and status["emailVerified"]
                        and author["is_active"]
                        and not (
                            author["is_muted"]
                            and (
                                author["muted_until"] is None
                                or author["muted_until"] > time.time()
                            )
                        )
                    )
                except AccountStatusUnavailable:
                    permitted = False
            if not permitted:
                explanation = "作者账号状态或发言资格无法确认，转人工复核并保持未公开"
                result = {
                    "jobId": job["jobId"],
                    "decision": "review",
                    "categories": ["uncertain"],
                    "evidence": [explanation],
                    "explanation": explanation,
                }
        if "submissionId" not in job:
            return super().complete(job, result, error, retry_at)
        with self.db(True) as conn:
            record = conn.execute(
                "SELECT j.*,s.content,s.status,s.kind,s.target_id,s.user_id,s.media_ids,s.metadata,s.id AS content_id FROM _moderation_content_jobs j JOIN _private_content_submissions s ON s.id=j.submission_id WHERE j.id=?",
                (job["id"],),
            ).fetchone()
            if (
                not record
                or record["state"] != "running"
                or record["lease_until"] < time.time()
                or not secrets.compare_digest(record["token"], job["token"])
                or record["status"] != "pending"
            ):
                return False
            media = conn.execute(
                "SELECT id,sha256 FROM _private_content_media WHERE submission_id=?",
                (record["submission_id"],),
            ).fetchall()
            order = json.loads(record["media_ids"])
            media = sorted(media, key=lambda m: order.index(m["id"]))
            if submission_hash(record["content"], media) != record["content_hash"]:
                conn.execute(
                    "UPDATE _moderation_content_jobs SET state='cancelled',token='' WHERE id=?",
                    (job["id"],),
                )
                return False
            if result is not None:
                verdict = validate_result(
                    result,
                    {**job, "currentComment": record["content"], "imageIds": order},
                )
                passed = verdict["decision"] == "allow"
                if passed:
                    row = dict(record)
                    row["id"] = record["content_id"]
                    publish(conn, row)
                else:
                    conn.execute(
                        "UPDATE _private_content_submissions SET status='review',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (record["submission_id"],),
                    )
                conn.execute(
                    "UPDATE _moderation_content_jobs SET state=?,result_json=?,token='',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (
                        "passed" if passed else "review",
                        json.dumps(verdict, ensure_ascii=False),
                        job["id"],
                    ),
                )
            else:
                quota = error == "quota_exhausted"
                state = "queued" if quota or record["attempts"] < 3 else "failed"
                conn.execute(
                    "UPDATE _moderation_content_jobs SET state=?,token='',attempts=attempts-?,ready_at=?,error_code=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (
                        state,
                        int(quota),
                        retry_at or time.time() + 60,
                        error[:80],
                        job["id"],
                    ),
                )
            return True

    def counts(self):
        counts = super().counts()
        with self.db() as conn:
            for row in conn.execute(
                "SELECT state,COUNT(*) n FROM _moderation_content_jobs GROUP BY state"
            ):
                counts[row["state"]] = counts.get(row["state"], 0) + row["n"]
        return counts


site = ReviewSite(connect, "wiki")


@router.get("/content-submissions")
def my_submissions(user=Depends(get_current_user), page: int = Query(1, ge=1)):
    with site.db() as conn:
        rows = conn.execute(
            """
        SELECT id,kind,target_id,content,media_ids,status,created_at,updated_at,decision_note
        FROM _private_content_submissions WHERE user_id=?
        UNION ALL
        SELECT 'comment:'||c.id,'comment',c.target_id,c.content,'[]',
          CASE WHEN c.status='deleted' THEN 'withdrawn' WHEN c.status='visible' THEN 'published'
               WHEN j.state='review' THEN 'review' ELSE 'pending' END,
          c.created_at,COALESCE(j.updated_at,c.created_at),COALESCE(j.final_note,'')
        FROM comments c LEFT JOIN _moderation_jobs j ON j.comment_id=c.id
        WHERE c.user_id=?
        ORDER BY created_at DESC,id DESC LIMIT 20 OFFSET ?
        """,
            (user["id"], user["id"], (page - 1) * 20),
        ).fetchall()
        data = []
        for row in rows:
            available = {
                m["id"]
                for m in conn.execute(
                    "SELECT id FROM _private_content_media WHERE submission_id=?",
                    (row["id"],),
                )
            }
            data.append(
                {
                    **dict(row),
                    "mediaIds": [
                        ident
                        for ident in json.loads(row["media_ids"])
                        if ident in available
                    ],
                }
            )
        return {"data": data}


@router.delete("/content-submissions/{submission_id}")
def withdraw(submission_id: str, user=Depends(get_current_user)):
    with site.db(True) as conn:
        row = conn.execute(
            "SELECT * FROM _private_content_submissions WHERE id=? AND user_id=?",
            (submission_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "提交不存在")
        if row["status"] == "published" and row["kind"] == "update":
            conn.execute(
                "DELETE FROM project_updates WHERE id=?",
                (f"{row['target_id']}:{row['id']}",),
            )
        if row["status"] == "published" and row["kind"] == "profile":
            raise HTTPException(409, "请提交新的个人简介替换已公开版本")
        conn.execute(
            "UPDATE _private_content_submissions SET status='withdrawn',updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (submission_id,),
        )
        conn.execute(
            "UPDATE _moderation_content_jobs SET state='cancelled',token='' WHERE submission_id=?",
            (submission_id,),
        )
    return {"ok": True}


@router.get("/content-media/{media_id}")
def private_media(media_id: str, request: Request):
    with site.db() as conn:
        row = conn.execute(
            "SELECT m.*,s.user_id,s.status FROM _private_content_media m JOIN _private_content_submissions s ON s.id=m.submission_id WHERE m.id=?",
            (media_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404)
        public = (
            row["status"] == "published"
            and conn.execute(
                "SELECT 1 FROM project_updates p,json_each(p.images) image WHERE image.value=? LIMIT 1",
                ("/api/content-media/" + media_id,),
            ).fetchone()
            is not None
        )
        if not public:
            user = get_optional_current_user(request, None)
            if not user or (user["id"] != row["user_id"] and user["role"] != "admin"):
                raise HTTPException(404)
        data = dict(row)
    try:
        payload = read_private_image(data)
    except Exception as exc:
        raise HTTPException(502, "图片暂时无法读取") from exc
    return Response(
        payload,
        media_type=data["mime"],
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


def require_admin(user=Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(403)
    return user


@router.get("/admin/content-review")
def review_cases(
    state: str = Query(
        "review", pattern="^(pending|review|published|rejected|withdrawn)$"
    ),
    page: int = Query(1, ge=1),
    admin=Depends(require_admin),
):
    with site.db() as conn:
        rows = conn.execute(
            "SELECT s.*,u.display_name AS author,u.username AS author_username,p.name AS target_title,j.state AS job_state,j.error_code,j.result_json FROM _private_content_submissions s JOIN users u ON u.id=s.user_id LEFT JOIN projects p ON s.kind='update' AND p.id=s.target_id JOIN _moderation_content_jobs j ON j.submission_id=s.id WHERE s.status=? ORDER BY s.created_at DESC,s.id DESC LIMIT 20 OFFSET ?",
            (state, (page - 1) * 20),
        ).fetchall()
        return {
            "data": [
                {
                    **dict(row),
                    "mediaIds": json.loads(row["media_ids"]),
                    "ai": json.loads(row["result_json"]),
                }
                for row in rows
            ]
        }


@router.post("/admin/content-review/{submission_id}/decision")
def decide(submission_id: str, payload: dict, admin=Depends(require_admin)):
    action, note = payload.get("action"), payload.get("note", "")
    if not isinstance(note, str):
        raise HTTPException(422, "处理原因必须是文字")
    note = note.strip()
    if action not in {"approve", "reject", "retry"} or not 1 <= len(note) <= 500:
        raise HTTPException(422, "请选择处理动作并填写 1–500 字原因")
    with site.db(True) as conn:
        row = conn.execute(
            "SELECT * FROM _private_content_submissions WHERE id=?", (submission_id,)
        ).fetchone()
        if not row or row["status"] not in {"pending", "review"}:
            raise HTTPException(409, "该内容已处理或撤回")
        if action == "approve":
            publish(conn, row, admin["id"])
        else:
            conn.execute(
                "UPDATE _private_content_submissions SET status=?,decided_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (
                    "pending" if action == "retry" else "rejected",
                    admin["id"],
                    submission_id,
                ),
            )
        conn.execute(
            "UPDATE _private_content_submissions SET decision_note=? WHERE id=?",
            (note, submission_id),
        )
        conn.execute(
            "UPDATE _moderation_content_jobs SET state=?,attempts=0,token='',ready_at=0,updated_at=CURRENT_TIMESTAMP WHERE submission_id=?",
            ("queued" if action == "retry" else "dismissed", submission_id),
        )
        conn.execute(
            "INSERT INTO governance_audit(actor_id,target_user_id,action,details) VALUES(?,?,?,?)",
            (
                admin["id"],
                row["user_id"],
                "content." + action,
                json.dumps({"id": submission_id, "note": note}, ensure_ascii=False),
            ),
        )
    return {"ok": True}


@router.post("/admin/users/{user_id}/mute")
def mute(user_id: int, payload: dict, admin=Depends(require_admin)):
    action, reason, days = (
        payload.get("action"),
        payload.get("reason", ""),
        payload.get("days", 0),
    )
    if not isinstance(reason, str):
        raise HTTPException(422, "处罚原因必须是文字")
    reason = reason.strip()
    if (
        action not in {"mute", "unmute"}
        or not 1 <= len(reason) <= 500
        or type(days) is not int
        or days not in {0, 1, 7, 30}
    ):
        raise HTTPException(422, "处罚动作、原因或期限无效")
    if user_id == admin["id"]:
        raise HTTPException(409, "不能禁言自己")
    with site.db(True) as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
            raise HTTPException(404)
        until = int(time.time()) + days * 86400 if days else None
        conn.execute(
            "UPDATE users SET is_muted=?,muted_until=?,mute_reason=? WHERE id=?",
            (
                int(action == "mute"),
                until if action == "mute" else None,
                reason if action == "mute" else "",
                user_id,
            ),
        )
        conn.execute(
            "INSERT INTO governance_audit(actor_id,target_user_id,action,details) VALUES(?,?,?,?)",
            (
                admin["id"],
                user_id,
                action,
                json.dumps({"reason": reason, "until": until}, ensure_ascii=False),
            ),
        )
    return {"ok": True}
