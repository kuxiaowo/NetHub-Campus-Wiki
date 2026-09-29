"""SQLite outbox, leased work and atomic human decisions; no network in transactions."""

import json
import secrets
import sqlite3
import time
from contextlib import contextmanager

from .policy import CATEGORIES, fingerprint, validate_result


def report_excerpt(value, limit=120):
    """Keep a short, single-line copy for a reporter notification."""
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _table_columns(conn, table):
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {
            row["name"] if isinstance(row, (sqlite3.Row, dict)) else row[1]
            for row in rows
        }
    except sqlite3.DatabaseError:
        return set()

SCHEMA = """
CREATE TABLE IF NOT EXISTS _moderation_jobs (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 comment_id INTEGER NOT NULL UNIQUE REFERENCES comments(id) ON DELETE CASCADE,
 content_hash TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'dispatch',
 attempts INTEGER NOT NULL DEFAULT 0,
 token TEXT NOT NULL DEFAULT '',
 ready_at REAL NOT NULL DEFAULT 0,
 lease_until REAL NOT NULL DEFAULT 0,
 result_json TEXT NOT NULL DEFAULT '{}',
 error_code TEXT NOT NULL DEFAULT '',
 config_version INTEGER,
 final_reasons TEXT NOT NULL DEFAULT '[]',
 final_note TEXT NOT NULL DEFAULT '',
 reviewed_by INTEGER,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_moderation_queue ON _moderation_jobs(state,ready_at,id);
CREATE TABLE IF NOT EXISTS system_notifications (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 recipient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 comment_id INTEGER NOT NULL,
 is_reply INTEGER NOT NULL,
 target_type TEXT NOT NULL,
 target_id INTEGER NOT NULL,
 target_title TEXT NOT NULL,
 reason_codes TEXT NOT NULL,
 reason_note TEXT NOT NULL DEFAULT '',
 original_excerpt TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 read_at TEXT,
 UNIQUE(recipient_id, comment_id)
);
CREATE INDEX IF NOT EXISTS idx_system_notifications_recipient ON system_notifications(recipient_id,id DESC);
"""


def enqueue(connection, comment_id):
    row = connection.execute(
        "SELECT content FROM comments WHERE id=?", (comment_id,)
    ).fetchone()
    connection.execute(
        "INSERT INTO _moderation_jobs(comment_id,content_hash) VALUES (?,?)",
        (comment_id, fingerprint(row["content"])),
    )


class Site:
    def __init__(self, connect, name):
        self.connect, self.name = connect, name

    @contextmanager
    def db(self, write=False):
        conn = self.connect()
        if not isinstance(conn, sqlite3.Connection):
            conn.close()
            raise RuntimeError("评论审核需要 SQLite 在线数据库")
        conn.row_factory = sqlite3.Row
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def release(self, comment_id):
        with self.db(True) as conn:
            conn.execute(
                "UPDATE _moderation_jobs SET state='queued' WHERE comment_id=? AND state='dispatch'",
                (comment_id,),
            )

    def target(self, conn, comment):
        if self.name == "cas":
            kind, ident, table, field, path = (
                "gallery",
                comment["gallery_id"],
                "galleries",
                "title",
                "/galleries/",
            )
        else:
            kind, ident = comment["target_type"], comment["target_id"]
            table, field, path = {
                "announcement": ("announcements", "title", "/announcement.html?id="),
                "project": ("projects", "name", "/detail.html?id="),
                "resource": ("resources", "title", "/resource.html?id="),
            }[kind]
        row = conn.execute(
            f"SELECT {field} AS title, * FROM {table} WHERE id=?", (ident,)
        ).fetchone()
        available = row is not None
        if row and kind in {"gallery", "announcement"}:
            available = row["status"] == "published"
        if row and kind == "announcement" and self.name == "wiki":
            available = (
                available
                and bool(row["published_at"])
                and row["published_at"]
                <= time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
            )
        return {
            "type": kind,
            "id": ident,
            "title": row["title"] if row else "原内容已不存在",
            "available": bool(available),
            "url": path + str(ident) if available else None,
        }

    def claim(self, version, timeout):
        now = time.time()
        with self.db(True) as conn:
            # Durable response callbacks interrupted by process exit become eligible.
            conn.execute(
                "UPDATE _moderation_jobs SET state='queued' WHERE state='dispatch' AND created_at <= datetime('now','-30 seconds')"
            )
            conn.execute(
                "UPDATE _moderation_jobs SET state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'queued' END, token='',error_code='worker_interrupted' WHERE state='running' AND lease_until<?",
                (now,),
            )
            row = conn.execute(
                "SELECT j.*, c.content, c.status FROM _moderation_jobs j JOIN comments c ON c.id=j.comment_id WHERE j.state='queued' AND j.ready_at<=? ORDER BY j.id LIMIT 1",
                (now,),
            ).fetchone()
            if row is None:
                return None
            if (
                row["status"] != "visible"
                or fingerprint(row["content"]) != row["content_hash"]
            ):
                conn.execute(
                    "UPDATE _moderation_jobs SET state='cancelled',token='' WHERE id=?",
                    (row["id"],),
                )
                return None
            comment = conn.execute(
                "SELECT * FROM comments WHERE id=?", (row["comment_id"],)
            ).fetchone()
            parent = (
                conn.execute(
                    "SELECT content,status FROM comments WHERE id=?",
                    (comment["parent_id"],),
                ).fetchone()
                if comment["parent_id"]
                else None
            )
            token = secrets.token_hex(24)
            conn.execute(
                "UPDATE _moderation_jobs SET state='running',attempts=attempts+1,token=?,lease_until=?,config_version=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (token, now + timeout + 60, version, row["id"]),
            )
            return {
                "id": row["id"],
                "jobId": f"{self.name}:{row['id']}:{token}",
                "token": token,
                "commentId": comment["id"],
                "currentComment": comment["content"],
                "parentComment": (
                    parent["content"]
                    if parent and parent["status"] == "visible"
                    else ""
                ),
                "pageTitle": self.target(conn, comment)["title"],
            }

    def complete(self, job, result=None, error="", retry_at=None):
        with self.db(True) as conn:
            row = conn.execute(
                "SELECT j.*,c.content,c.status FROM _moderation_jobs j JOIN comments c ON c.id=j.comment_id WHERE j.id=?",
                (job["id"],),
            ).fetchone()
            if (
                row is None
                or row["state"] != "running"
                or row["lease_until"] < time.time()
                or not secrets.compare_digest(row["token"], job["token"])
            ):
                return False
            if (
                row["status"] != "visible"
                or fingerprint(row["content"]) != row["content_hash"]
            ):
                conn.execute(
                    "UPDATE _moderation_jobs SET state='cancelled',token='' WHERE id=?",
                    (row["id"],),
                )
                return False
            if result is not None:
                validated = validate_result(
                    result, {**job, "currentComment": row["content"]}
                )
                state = "review" if validated["decision"] == "review" else "passed"
                if state == "review":
                    conn.execute(
                        "UPDATE comments SET status='hidden' WHERE id=?",
                        (row["comment_id"],),
                    )
                conn.execute(
                    "UPDATE _moderation_jobs SET state=?,result_json=?,error_code='',token='',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (state, json.dumps(validated, ensure_ascii=False), row["id"]),
                )
            else:
                quota = error == "quota_exhausted"
                state = "queued" if quota or row["attempts"] < 3 else "failed"
                delay = 10 if row["attempts"] == 1 else 60
                conn.execute(
                    "UPDATE _moderation_jobs SET state=?,ready_at=?,error_code=?,attempts=attempts-?,token='',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (
                        state,
                        retry_at or time.time() + delay,
                        error[:80],
                        int(quota),
                        row["id"],
                    ),
                )
            return True

    def _decision(self, conn, comment, admin, action, reasons, note):
        if action not in {"ignore", "delete"}:
            raise ValueError("处理动作无效")
        if action == "delete":
            if (
                not isinstance(reasons, list)
                or not reasons
                or any(
                    not isinstance(r, str) or r not in {*CATEGORIES, "other"}
                    for r in reasons
                )
            ):
                raise ValueError("请选择有效删除原因")
            if (
                not isinstance(note, str)
                or len(note) > 1000
                or ("other" in reasons and not note.strip())
            ):
                raise ValueError("其他原因必须填写说明，说明最多1000字")
        job = conn.execute(
            "SELECT * FROM _moderation_jobs WHERE comment_id=?", (comment["id"],)
        ).fetchone()
        if comment["status"] == "deleted" or (
            job and job["state"] in {"dismissed", "deleted"} and action == "ignore"
        ):
            return
        if action == "ignore":
            if not job or job["state"] not in {"review", "failed"}:
                raise ValueError("仅待复核或审核失败记录可以忽略")
            if job["state"] == "review":
                conn.execute(
                    "UPDATE comments SET status='visible' WHERE id=? AND status='hidden'",
                    (comment["id"],),
                )
            conn.execute(
                "UPDATE _moderation_jobs SET state='dismissed',token='',reviewed_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (admin, job["id"]),
            )
            return
        target = self.target(conn, comment)
        pending_reports = []
        report_columns = _table_columns(conn, "comment_reports")
        if self.name == "wiki" and {"id", "reporter_id"}.issubset(report_columns) and _table_columns(conn, "report_notifications"):
            pending_reports = conn.execute(
                "SELECT id,reporter_id FROM comment_reports WHERE comment_id=? AND status='pending'",
                (comment["id"],),
            ).fetchall()
        conn.execute(
            "UPDATE comments SET content='',status='deleted' WHERE id=?",
            (comment["id"],),
        )
        if not job:
            conn.execute(
                "INSERT INTO _moderation_jobs(comment_id,content_hash,state) VALUES (?,?,'deleted')",
                (comment["id"], fingerprint("")),
            )
        # Retain the AI categories and explanation, never its quoted evidence after deletion.
        ai = json.loads(job["result_json"]) if job else {}
        ai.pop("evidence", None)
        conn.execute(
            "UPDATE _moderation_jobs SET state='deleted',token='',result_json=?,final_reasons=?,final_note=?,reviewed_by=?,updated_at=CURRENT_TIMESTAMP WHERE comment_id=?",
            (
                json.dumps(ai, ensure_ascii=False),
                json.dumps(reasons),
                note.strip(),
                admin,
                comment["id"],
            ),
        )
        if self.name == "wiki":
            conn.execute(
                "UPDATE comment_reports SET status='resolved',decision='deleted',review_note='',resolved_by=?,resolved_at=CURRENT_TIMESTAMP WHERE comment_id=? AND status='pending'",
                (admin, comment["id"]),
            )
            for report in pending_reports:
                conn.execute(
                    """INSERT INTO report_notifications
                       (recipient_id,content_type,report_id,original_excerpt,decision,note,
                        target_type,target_id,target_title)
                       VALUES (?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(content_type,report_id,recipient_id) DO UPDATE SET
                         decision=excluded.decision,original_excerpt=excluded.original_excerpt,
                         note=excluded.note,created_at=CURRENT_TIMESTAMP,read_at=NULL""",
                    (
                        report["reporter_id"], "comment", report["id"],
                        report_excerpt(comment["content"]), "deleted", note.strip(),
                        target["type"], target["id"], target["title"],
                    ),
                )
        notification_values = (
            comment["user_id"], comment["id"], int(comment["parent_id"] is not None),
            target["type"], target["id"], target["title"],
            json.dumps(reasons), note.strip(),
        )
        if "original_excerpt" in _table_columns(conn, "system_notifications"):
            conn.execute(
                "INSERT OR IGNORE INTO system_notifications(recipient_id,comment_id,is_reply,target_type,target_id,target_title,reason_codes,reason_note,original_excerpt) VALUES (?,?,?,?,?,?,?,?,?)",
                (*notification_values, report_excerpt(comment["content"])),
            )
        else:
            conn.execute(
                "INSERT OR IGNORE INTO system_notifications(recipient_id,comment_id,is_reply,target_type,target_id,target_title,reason_codes,reason_note) VALUES (?,?,?,?,?,?,?,?)",
                notification_values,
            )

    def decide(self, case_id, admin, action, reasons=None, note=""):
        with self.db(True) as conn:
            row = conn.execute(
                "SELECT c.* FROM comments c JOIN _moderation_jobs j ON j.comment_id=c.id WHERE j.id=?",
                (case_id,),
            ).fetchone()
            if row is None:
                raise LookupError("审核记录不存在")
            self._decision(conn, row, admin, action, reasons or [], note)

    def delete(self, comment_id, admin, reasons, note="", conn=None):
        if conn is None:
            with self.db(True) as opened:
                return self.delete(comment_id, admin, reasons, note, opened)
        row = conn.execute(
            "SELECT * FROM comments WHERE id=?", (comment_id,)
        ).fetchone()
        if row is None:
            raise LookupError("留言不存在")
        self._decision(conn, row, admin, "delete", reasons, note)

    def cancel(self, conn, comment_id):
        conn.execute(
            "UPDATE _moderation_jobs SET state='cancelled',token='',result_json='{}' WHERE comment_id=? AND state NOT IN ('deleted','dismissed')",
            (comment_id,),
        )

    def retry(self, case_id):
        with self.db(True) as conn:
            changed = conn.execute(
                "UPDATE _moderation_jobs SET state='queued',attempts=0,ready_at=0,error_code='',token='' WHERE id=? AND state='failed' AND EXISTS(SELECT 1 FROM comments WHERE id=_moderation_jobs.comment_id AND status='visible')",
                (case_id,),
            ).rowcount
            if not changed:
                raise ValueError("仅公开且审核失败的评论可以重试")

    def cases(self, state, page, size):
        where = (
            "j.state IN ('passed','dismissed','deleted','cancelled')"
            if state == "history"
            else "j.state=?"
        )
        params = [] if state == "history" else [state]
        with self.db() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM _moderation_jobs j WHERE {where}", params
            ).fetchone()[0]
            rows = conn.execute(
                f"SELECT j.*,c.content,c.parent_id,c.user_id,c.status,u.display_name FROM _moderation_jobs j JOIN comments c ON c.id=j.comment_id JOIN users u ON u.id=c.user_id WHERE {where} ORDER BY j.id DESC LIMIT ? OFFSET ?",
                [*params, size, (page - 1) * size],
            ).fetchall()
            data = []
            for row in rows:
                comment = conn.execute(
                    "SELECT * FROM comments WHERE id=?", (row["comment_id"],)
                ).fetchone()
                parent = (
                    conn.execute(
                        "SELECT content,status FROM comments WHERE id=?",
                        (row["parent_id"],),
                    ).fetchone()
                    if row["parent_id"]
                    else None
                )
                data.append(
                    {
                        "id": row["id"],
                        "commentId": row["comment_id"],
                        "state": row["state"],
                        "content": row["content"],
                        "parentContent": (
                            parent["content"]
                            if parent and parent["status"] != "deleted"
                            else ""
                        ),
                        "author": row["display_name"],
                        "target": self.target(conn, comment),
                        "ai": json.loads(row["result_json"]),
                        "attempts": row["attempts"],
                        "error": row["error_code"],
                        "finalReasons": json.loads(row["final_reasons"]),
                        "finalNote": row["final_note"],
                        "reviewedBy": row["reviewed_by"],
                        "configVersion": row["config_version"],
                        "createdAt": row["created_at"],
                        "updatedAt": row["updated_at"],
                    }
                )
            return {
                "data": data,
                "page": page,
                "hasMore": page * size < total,
                "total": total,
            }

    def counts(self):
        with self.db() as conn:
            return {
                row["state"]: row["n"]
                for row in conn.execute(
                    "SELECT state,COUNT(*) n FROM _moderation_jobs GROUP BY state"
                )
            }

    def notifications(self, user, page, size):
        with self.db() as conn:
            window = page * size
            count, latest = conn.execute(
                "SELECT COUNT(*),COALESCE(MAX(id),0) FROM system_notifications WHERE recipient_id=?",
                (user,),
            ).fetchone()
            rows = conn.execute(
                "SELECT * FROM system_notifications WHERE recipient_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
                (user, window, 0),
            ).fetchall()
            system_columns = _table_columns(conn, "system_notifications")
            report_rows = []
            report_total = 0
            report_latest = 0
            if _table_columns(conn, "report_notifications"):
                report_rows = conn.execute(
                    "SELECT * FROM report_notifications WHERE recipient_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
                    (user, window, 0),
                ).fetchall()
                report_total, report_latest = conn.execute(
                    "SELECT COUNT(*),COALESCE(MAX(id),0) FROM report_notifications WHERE recipient_id=?", (user,)
                ).fetchone()
            data = []
            for row in rows:
                synthetic = (
                    {"gallery_id": row["target_id"]}
                    if self.name == "cas"
                    else {
                        "target_type": row["target_type"],
                        "target_id": row["target_id"],
                    }
                )
                target = self.target(conn, synthetic)
                target["title"] = row["target_title"]
                codes = json.loads(row["reason_codes"])
                data.append(
                    {
                        "id": row["id"],
                        "title": "回复处理通知" if row["is_reply"] else "评论处理通知",
                        "commentId": row["comment_id"],
                        "target": target,
                        "reasonCodes": codes,
                        "reasons": [CATEGORIES.get(c, "其他") for c in codes],
                        "note": row["reason_note"],
                        "excerpt": row["original_excerpt"] if "original_excerpt" in system_columns else "",
                        "createdAt": row["created_at"],
                        "read": row["read_at"] is not None,
                    }
                )
            for row in report_rows:
                data.append(
                    {
                        "id": row["id"],
                        "type": "report",
                        "title": "私信处理通知" if row["audience"] == "author" else "举报处理通知",
                        "decision": row["decision"],
                        "audience": row["audience"],
                        "excerpt": row["original_excerpt"],
                        "note": row["note"],
                        "reasonCodes": json.loads(row["reason_codes"]),
                        "target": {
                            "type": row["target_type"],
                            "id": row["target_id"],
                            "title": row["target_title"] or "私信",
                            "available": False,
                            "url": None,
                        },
                        "createdAt": row["created_at"],
                        "read": row["read_at"] is not None,
                    }
                )
            data.sort(key=lambda item: (item.get("createdAt") or "", item["id"]), reverse=True)
            start = (page - 1) * size
            data = data[start:start + size]
            return {
                "data": data,
                "page": page,
                "hasMore": page * size < count + report_total,
                "latestId": max(latest, report_latest),
                "latestSystemId": latest,
                "latestReportId": report_latest,
            }

    def read(self, user, through, report_through=None):
        with self.db(True) as conn:
            conn.execute(
                "UPDATE system_notifications SET read_at=CURRENT_TIMESTAMP WHERE recipient_id=? AND id<=? AND read_at IS NULL",
                (user, through),
            )
            if _table_columns(conn, "report_notifications"):
                conn.execute(
                    "UPDATE report_notifications SET read_at=CURRENT_TIMESTAMP WHERE recipient_id=? AND id<=? AND read_at IS NULL",
                    (user, through if report_through is None else report_through),
                )

    def unread(self, user):
        with self.db() as conn:
            regular = conn.execute(
                "SELECT COUNT(*) FROM system_notifications WHERE recipient_id=? AND read_at IS NULL",
                (user,),
            ).fetchone()[0]
            reports = 0
            if _table_columns(conn, "report_notifications"):
                reports = conn.execute(
                    "SELECT COUNT(*) FROM report_notifications WHERE recipient_id=? AND read_at IS NULL",
                    (user,),
                ).fetchone()[0]
            return regular + reports
