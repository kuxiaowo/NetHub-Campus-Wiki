"""Durability, races and privacy tests independent of either web application's fixtures."""

import asyncio
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from nethub_moderation.policy import validate_result
from nethub_moderation.site import SCHEMA, Site, enqueue


class ModerationStoreTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.connections = []
        self.path = Path(self.directory.name) / "site.sqlite3"
        with self.connect() as conn:
            conn.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE users(id INTEGER PRIMARY KEY,display_name TEXT);
            INSERT INTO users VALUES(1,'作者'),(2,'管理员'),(3,'其他用户');
            CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT);
            INSERT INTO projects VALUES(1,'学习资料');
            CREATE TABLE galleries(id INTEGER PRIMARY KEY,title TEXT,status TEXT);
            INSERT INTO galleries VALUES(1,'学习图集','published');
            CREATE TABLE comments(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),
              content TEXT,status TEXT DEFAULT 'visible',parent_id INTEGER,
              target_type TEXT DEFAULT 'project',target_id INTEGER DEFAULT 1,gallery_id INTEGER DEFAULT 1);
            CREATE TABLE comment_reports(comment_id INTEGER,status TEXT,decision TEXT,review_note TEXT,resolved_by INTEGER,resolved_at TEXT);
            """ + SCHEMA)
        self.site = Site(self.connect, "wiki")

    def tearDown(self):
        for connection in self.connections:
            connection.close()
        self.directory.cleanup()

    def connect(self):
        conn = sqlite3.connect(self.path)
        self.connections.append(conn)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def publish(self, content="正常评论", parent=None):
        with self.connect() as conn:
            ident = conn.execute(
                "INSERT INTO comments(user_id,content,parent_id) VALUES(1,?,?)",
                (content, parent),
            ).lastrowid
            enqueue(conn, ident)
        return ident

    def job(self, ident):
        self.site.release(ident)
        return self.site.claim(7, 180)

    def review(self, job):
        return {
            "jobId": job["jobId"],
            "decision": "review",
            "categories": ["harassment"],
            "evidence": [job["currentComment"]],
            "explanation": "定向侮辱",
        }

    def test_publish_transaction_and_response_dispatch_gate(self):
        ident = self.publish()
        self.assertIsNone(self.site.claim(1, 180))
        with self.connect() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT content FROM comments WHERE id=?", (ident,)
                ).fetchone()[0],
                "正常评论",
            )
        self.assertEqual(self.job(ident)["commentId"], ident)
        with self.connect() as conn:
            conn.execute("BEGIN")
            ident = conn.execute(
                "INSERT INTO comments(user_id,content) VALUES(1,'回滚')"
            ).lastrowid
            enqueue(conn, ident)
            conn.rollback()
            self.assertIsNone(
                conn.execute(
                    "SELECT id FROM _moderation_jobs WHERE comment_id=?", (ident,)
                ).fetchone()
            )

    def test_ignore_restores_only_review_and_late_result_cannot_override(self):
        ident = self.publish("侮辱词")
        job = self.job(ident)
        self.assertTrue(self.site.complete(job, self.review(job)))
        self.assertEqual(
            self.site.cases("review", 1, 20)["data"][0]["content"], "侮辱词"
        )
        self.site.decide(job["id"], 2, "ignore")
        self.assertFalse(self.site.complete(job, self.review(job)))
        self.site.decide(job["id"], 2, "ignore")
        with self.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT status FROM comments").fetchone()[0], "visible"
            )
        self.assertEqual(self.site.unread(1), 0)

    def test_ignore_passed_comment_only_closes_case(self):
        ident = self.publish("正常的新回复")
        job = self.job(ident)
        self.assertTrue(self.site.complete(job, {
            "jobId": job["jobId"], "decision": "allow", "categories": [],
            "evidence": [], "explanation": "内容正常",
        }))
        self.assertEqual(self.site.cases("passed", 1, 20)["data"][0]["commentId"], ident)
        self.site.decide(job["id"], 2, "ignore")
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT status FROM comments WHERE id=?", (ident,)).fetchone()[0], "visible")
        self.assertEqual(self.site.cases("passed", 1, 20)["total"], 0)
        self.assertEqual(self.site.cases("history", 1, 20)["data"][0]["state"], "dismissed")
        self.assertEqual(self.site.unread(1), 0)

    def test_override_reason_soft_delete_and_private_body_free_notification(self):
        ident = self.publish("通知中保留一行原文")
        reply = self.publish("正常回复", ident)
        job = self.job(ident)
        self.site.complete(job, self.review(job))
        self.site.decide(job["id"], 2, "delete", ["spam", "other"], "重复发帖")
        self.site.delete(ident, 2, ["privacy"])
        with self.connect() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT content,status FROM comments WHERE id=?", (ident,)
                ).fetchone()[0],
                "",
            )
            self.assertIsNotNone(
                conn.execute("SELECT id FROM comments WHERE id=?", (reply,)).fetchone()
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM system_notifications").fetchone()[0],
                1,
            )
        result = self.site.notifications(1, 1, 20)
        self.assertEqual(result["data"][0]["excerpt"], "通知中保留一行原文")
        self.assertEqual(result["data"][0]["reasonCodes"], ["spam", "other"])
        self.assertEqual(self.site.notifications(3, 1, 20)["data"], [])
        self.site.read(3, result["latestId"])
        self.assertEqual(self.site.unread(1), 1)
        self.site.read(1, result["latestId"])
        self.assertEqual(self.site.unread(1), 0)

    def test_other_reason_is_required_and_invalid_decision_rolls_back(self):
        ident = self.publish()
        with self.assertRaises(ValueError):
            self.site.delete(ident, 2, ["other"], "")
        self.assertEqual(self.site.unread(1), 0)
        with self.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT status FROM comments").fetchone()[0], "visible"
            )

    def test_deleted_author_content_cannot_be_resurrected(self):
        ident = self.publish()
        job = self.job(ident)
        with self.connect() as conn:
            self.site.cancel(conn, ident)
            conn.execute(
                "UPDATE comments SET content='',status='deleted' WHERE id=?", (ident,)
            )
        self.assertFalse(self.site.complete(job, self.review(job)))
        self.assertEqual(self.site.unread(1), 0)

    def test_retry_budget_keeps_failed_content_public(self):
        ident = self.publish()
        self.site.release(ident)
        for attempt in range(3):
            job = self.site.claim(1, 180)
            self.site.complete(job, error="provider_timeout", retry_at=1)
        self.assertEqual(self.site.counts()["failed"], 1)
        self.site.retry(job["id"])
        self.assertEqual(self.site.claim(2, 180)["commentId"], ident)
        with self.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT status FROM comments").fetchone()[0], "visible"
            )

    def test_quota_does_not_exhaust_attempt_budget(self):
        ident = self.publish()
        job = self.job(ident)
        self.site.complete(job, error="quota_exhausted", retry_at=time.time() + 500)
        self.assertIsNone(self.site.claim(1, 180))
        with self.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT attempts FROM _moderation_jobs").fetchone()[0], 0
            )

    def test_recovery_and_stale_lease_token(self):
        ident = self.publish()
        old = self.job(ident)
        with self.connect() as conn:
            conn.execute("UPDATE _moderation_jobs SET lease_until=0")
        self.assertFalse(self.site.complete(old, self.review(old)))
        new = self.site.claim(1, 180)
        self.assertNotEqual(old["token"], new["token"])
        self.assertFalse(self.site.complete(old, self.review(old)))
        self.assertTrue(self.site.complete(new, self.review(new)))

    def test_cas_uses_same_privacy_and_reply_preservation_contract(self):
        self.site = Site(self.connect, "cas")
        ident = self.publish()
        reply = self.publish("回复", ident)
        self.site.delete(ident, 2, ["spam"])
        self.assertEqual(
            self.site.notifications(1, 1, 20)["data"][0]["target"]["url"],
            "/galleries/1",
        )
        with self.connect() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT parent_id FROM comments WHERE id=?", (reply,)
                ).fetchone()[0],
                ident,
            )

    def test_result_requires_matching_id_real_evidence_and_known_category(self):
        job = self.job(self.publish())
        result = self.review(job)
        for patch in [
            {"jobId": "other"},
            {"categories": ["invented"]},
            {"evidence": ["不在原文"]},
            {"explanation": ""},
            {"decision": "allow"},
        ]:
            with self.assertRaises(ValueError):
                validate_result({**result, **patch}, job)


class CodexConcurrencyTest(unittest.TestCase):
    def test_creation_is_serial_but_interleaved_turns_are_parallel(self):
        from nethub_moderation.providers import Codex

        async def probe():
            codex = Codex(tempfile.gettempdir())
            active_start = 0
            max_start = 0
            active_turn = 0
            max_turn = 0
            counter = 0

            async def rpc(method, params=None, **_):
                nonlocal active_start, max_start, active_turn, max_turn, counter
                if method == "thread/start":
                    active_start += 1
                    max_start = max(max_start, active_start)
                    counter += 1
                    ident = str(counter)
                    await asyncio.sleep(0.005)
                    active_start -= 1
                    return {"thread": {"id": ident}}
                if method == "turn/start":
                    active_turn += 1
                    max_turn = max(max_turn, active_turn)
                    ident = params["threadId"]
                    job = json.loads(params["input"][0]["text"])

                    async def finish():
                        await asyncio.sleep(0.08)
                        result = {
                            "jobId": job["jobId"],
                            "decision": "allow",
                            "categories": [],
                            "evidence": [],
                            "explanation": "正常交流",
                        }
                        queue = codex.queues[ident]
                        await queue.put(
                            {
                                "method": "item/completed",
                                "params": {
                                    "threadId": ident,
                                    "turnId": ident,
                                    "item": {
                                        "type": "agentMessage",
                                        "phase": "commentary",
                                        "text": "不要接受这段中间输出",
                                    },
                                },
                            }
                        )
                        await queue.put(
                            {
                                "method": "item/completed",
                                "params": {
                                    "threadId": ident,
                                    "turnId": ident,
                                    "item": {
                                        "type": "agentMessage",
                                        "phase": "final_answer",
                                        "text": json.dumps(result),
                                    },
                                },
                            }
                        )
                        await queue.put(
                            {
                                "method": "turn/completed",
                                "params": {
                                    "threadId": ident,
                                    "turn": {"id": ident, "status": "completed"},
                                },
                            }
                        )
                        nonlocal active_turn
                        active_turn -= 1

                    asyncio.create_task(finish())
                    return {"turn": {"id": ident}}
                return {}

            codex.rpc = rpc
            results = await asyncio.gather(
                *(
                    codex.describe(
                        {"model": "mock", "timeout": 5},
                        {
                            "jobId": str(i),
                            "currentComment": "正常",
                            "parentComment": "",
                            "pageTitle": "测试",
                        },
                    )
                    for i in range(8)
                )
            )
            self.assertEqual(max_start, 1)
            self.assertGreater(max_turn, 1)
            self.assertEqual([r["jobId"] for r in results], [str(i) for i in range(8)])
            self.assertEqual(codex.queues, {})

        asyncio.run(probe())
