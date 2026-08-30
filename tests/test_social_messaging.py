"""用户、管理员维护的人员绑定和私信主流程集成测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image

_TEMP_DIR = tempfile.TemporaryDirectory()
os.environ["DATABASE_PATH"] = str(Path(_TEMP_DIR.name) / "campus_wiki_test.db")
os.environ["AUTH_SECRET_KEY"] = "test-secret-key-with-at-least-32-bytes"

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.bootstrap_admin import create_initial_admin  # noqa: E402
from backend.database import _backfill_project_members, get_db_connection  # noqa: E402
from backend.view_tracking import clear_tracked_views  # noqa: E402


class SocialMessagingFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.database_path = Path(_TEMP_DIR.name) / "campus_wiki_test.db"
        cls.database_path_patcher = patch(
            "backend.database.get_database_path", return_value=cls.database_path
        )
        cls.database_path_patcher.start()
        cls.project_asset_dir = Path(__file__).resolve().parents[1] / "public" / "CAS" / "__test_project_assets__"
        cls.project_asset_dir.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 8), "blue").save(cls.project_asset_dir / "icon.png")
        Image.new("RGB", (8, 8), "red").save(cls.project_asset_dir / "activity-1.jpg")
        Image.new("RGB", (8, 8), "green").save(cls.project_asset_dir / "activity-2.jpg")
        (cls.project_asset_dir / "no-icon").mkdir(exist_ok=True)
        upload_buffer = io.BytesIO()
        Image.new("RGB", (10, 10), "purple").save(upload_buffer, format="PNG")
        cls.upload_photo = upload_buffer.getvalue()
        cls._create_explicit_test_fixtures()
        create_initial_admin("test_admin", "test-admin-password-123", "Test Admin")
        cls._create_migrated_test_fixtures()
        cls.client = TestClient(app)
        cls.admin_token = cls._login("test_admin", "test-admin-password-123")
        settings_response = cls.client.patch(
            "/api/admin/auth-security-settings",
            headers=cls._headers(cls.admin_token),
            json={
                "loginIpLimit": 10000,
                "adminLoginIpLimit": 10000,
                "loginFailureLimit": 10000,
                "registerHourlyLimit": 10000,
                "registerDailyLimit": 10000,
                "passwordChangeHourlyLimit": 10000,
            },
        )
        assert settings_response.status_code == 200, settings_response.text
        cls.alice = cls._register("alice_user", "Alice")
        cls.bob = cls._register("bob_user", "Bob")
        cls.charlie = cls._register("charlie_user", "Charlie")
        cls.alice_token = cls._login("alice_user", "password123")
        cls.bob_token = cls._login("bob_user", "password123")
        cls.charlie_token = cls._login("charlie_user", "password123")

    @classmethod
    def _create_explicit_test_fixtures(cls) -> None:
        """Create v1-only fixtures before migrations exercise member backfill."""

        schema_path = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"
        connection = sqlite3.connect(cls.database_path)
        try:
            connection.executescript(schema_path.read_text(encoding="utf-8"))
            connection.execute(
                """
                INSERT INTO projects
                  (id, name, leader, members, category, year, icon, description,
                   media, cas_creativity, cas_activity, cas_service, popularity, updates)
                VALUES
                  (1, '测试项目', '李明', '李明, 王小雨, Chen Alex', '测试分类',
                   2026, '', '仅供集成测试使用', '[]', 1, 1, 1, 0, '[]')
                """
            )
            connection.execute(
                """
                INSERT INTO resources
                  (id, title, description, year, category, label, image, resource_url)
                VALUES
                  (1, '测试资源', '仅供集成测试使用', 2026, 'other',
                   '其他资源', 'https://example.com/cover.png',
                   'https://example.com/resource.pdf')
                """
            )
            connection.commit()
        finally:
            connection.close()

    @classmethod
    def _create_migrated_test_fixtures(cls) -> None:
        """Insert content that belongs to tables created by later migrations."""

        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO announcements
                      (title, summary, content, status, is_pinned, published_at)
                    VALUES (%s, %s, %s, 'published', %s, CURRENT_TIMESTAMP)
                    """,
                    [
                        ("测试公告一", "第一条测试摘要", "第一条测试正文", 1),
                        ("测试公告二", "第二条测试摘要", "第二条测试正文", 0),
                        ("测试公告三", "第三条测试摘要", "第三条测试正文", 0),
                    ],
                )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.project_asset_dir, ignore_errors=True)
        cls.client.close()
        cls.database_path_patcher.stop()

    @classmethod
    def _register(cls, username: str, display_name: str) -> dict:
        response = cls.client.post(
            "/api/auth/register",
            json={"username": username, "password": "password123", "displayName": display_name},
        )
        assert response.status_code == 200, response.text
        return response.json()

    @classmethod
    def _login(cls, username: str, password: str) -> str:
        response = cls.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        assert response.status_code == 200, response.text
        return response.json()["accessToken"]

    @staticmethod
    def _headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    @classmethod
    def _seed_business_fixtures(cls) -> None:
        """测试自行准备业务数据，不依赖生产数据库初始化脚本。"""

        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO projects
                      (id, name, leader, members, category, year, description)
                    VALUES
                      (1, '测试项目', '李明', '李明, 王小雨, Chen Alex',
                       '测试分类', 2026, '集成测试项目')
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO resources
                      (id, title, description, year, category, label, image, resource_url)
                    VALUES
                      (1, '测试资源', '集成测试资源', 2026, 'other', '其他资源',
                       'https://example.com/test-cover.png',
                       'https://example.com/test-resource.pdf')
                    """
                )
                cursor.executemany(
                    """
                    INSERT INTO announcements
                      (id, title, summary, content, status, is_pinned, published_at)
                    VALUES (%s, %s, %s, %s, 'published', %s, CURRENT_TIMESTAMP)
                    """,
                    [
                        (1, "测试公告一", "测试摘要一", "测试内容一", 1),
                        (2, "测试公告二", "测试摘要二", "测试内容二", 0),
                    ],
                )
            _backfill_project_members(connection._connection)

    def test_00_password_length_limits_cover_all_auth_endpoints(self) -> None:
        maximum_password = "a" * 128
        replacement_password = "b" * 128
        oversized_password = "c" * 129

        registered = self.client.post(
            "/api/auth/register",
            json={
                "username": "max_password_user",
                "password": maximum_password,
                "displayName": "Password Limit",
            },
        )
        self.assertEqual(registered.status_code, 200, registered.text)

        login = self.client.post(
            "/api/auth/login",
            json={"username": "max_password_user", "password": maximum_password},
        )
        self.assertEqual(login.status_code, 200, login.text)
        token = login.json()["accessToken"]

        changed = self.client.patch(
            "/api/auth/password",
            headers=self._headers(token),
            json={"currentPassword": maximum_password, "newPassword": replacement_password},
        )
        self.assertEqual(changed.status_code, 200, changed.text)

        rejected_requests = [
            self.client.post(
                "/api/auth/register",
                json={"username": "oversized_register", "password": oversized_password},
            ),
            self.client.post(
                "/api/auth/login",
                json={"username": "max_password_user", "password": oversized_password},
            ),
            self.client.patch(
                "/api/auth/password",
                headers=self._headers(token),
                json={"currentPassword": oversized_password, "newPassword": replacement_password},
            ),
            self.client.patch(
                "/api/auth/password",
                headers=self._headers(token),
                json={"currentPassword": replacement_password, "newPassword": oversized_password},
            ),
            self.client.post(
                "/api/admin/users",
                headers=self._headers(self.admin_token),
                json={"username": "oversized_admin", "password": oversized_password},
            ),
        ]
        for response in rejected_requests:
            self.assertEqual(response.status_code, 422, response.text)

    def test_00_resource_types_are_fixed_in_code(self) -> None:
        expected = [
            {"value": "yearbook", "label": "Yearbook", "sortOrder": 10},
            {"value": "photos", "label": "活动照片", "sortOrder": 20},
            {"value": "teacher", "label": "老师驾到", "sortOrder": 30},
            {"value": "other", "label": "其他资源", "sortOrder": 999},
        ]
        response = self.client.get("/api/resources/meta")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["categories"], expected)

        response = self.client.get(
            "/api/admin/resource-categories",
            headers=self._headers(self.admin_token),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["data"],
            [{**resource_type, "isActive": True} for resource_type in expected],
        )

        response = self.client.post(
            "/api/admin/resources",
            headers=self._headers(self.admin_token),
            json={
                "title": "固定类型测试资源",
                "year": 2026,
                "category": "other",
                "label": "不能覆盖固定名称",
                "hot": 99,
                "image": "https://example.com/cover.png",
                "resourceUrl": "https://example.com/resource.pdf",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        other_resource = response.json()
        self.assertEqual(other_resource["category"], "other")
        self.assertEqual(other_resource["label"], "其他资源")
        self.assertEqual(other_resource["hot"], 0)

        response = self.client.get(
            f"/api/resources/{other_resource['id']}",
            headers=self._headers(self.admin_token),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"]["hot"], 1)
        response = self.client.get(
            f"/api/resources/{other_resource['id']}",
            headers=self._headers(self.admin_token),
        )
        self.assertEqual(response.json()["data"]["hot"], 1)

        response = self.client.patch(
            f"/api/admin/resources/{other_resource['id']}",
            headers=self._headers(self.admin_token),
            json={"hot": 50},
        )
        self.assertEqual(response.status_code, 422, response.text)

        response = self.client.post(
            "/api/admin/resources",
            headers=self._headers(self.admin_token),
            json={
                "title": "老师课堂测试视频",
                "description": "测试老师驾到视频资源的创建和筛选。",
                "year": 2026,
                "category": "teacher",
                "image": "https://example.com/images/teacher-class-cover.webp",
                "resourceUrl": "https://example.com/videos/teacher-class.mp4",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        teacher_resource = response.json()
        self.assertEqual(teacher_resource["category"], "teacher")
        self.assertEqual(teacher_resource["label"], "老师驾到")
        self.assertEqual(teacher_resource["image"], "https://example.com/images/teacher-class-cover.webp")
        self.assertEqual(teacher_resource["year"], 2026)
        self.assertEqual(teacher_resource["hot"], 0)
        self.assertEqual(teacher_resource["downloads"], 0)

        response = self.client.get("/api/resources?category=teacher")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item["id"] for item in response.json()["data"]], [teacher_resource["id"]])

        response = self.client.post(
            "/api/admin/resources",
            headers=self._headers(self.admin_token),
            json={
                "title": "未填写简介和封面的视频",
                "year": 2026,
                "category": "teacher",
                "resourceUrl": "https://example.com/videos/missing-description.mp4",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        teacher_without_optional_fields = response.json()
        self.assertEqual(teacher_without_optional_fields["description"], "")
        self.assertEqual(teacher_without_optional_fields["image"], "")

        response = self.client.patch(
            f"/api/admin/resources/{teacher_resource['id']}",
            headers=self._headers(self.admin_token),
            json={"description": "", "image": ""},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["description"], "")
        self.assertEqual(response.json()["image"], "")

        response = self.client.post(
            "/api/admin/photo-activities",
            headers=self._headers(self.admin_token),
            json={
                "activity": "自动热度测试活动",
                "description": "验证新活动热度固定从零开始。",
                "year": 2026,
                "hot": 88,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        activity = response.json()
        self.assertEqual(activity["hot"], 0)

        response = self.client.get(
            f"/api/photo-activities/{activity['id']}/photos",
            headers=self._headers(self.admin_token),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["activity"]["hot"], 1)
        response = self.client.get(
            f"/api/photo-activities/{activity['id']}/photos",
            headers=self._headers(self.admin_token),
        )
        self.assertEqual(response.json()["activity"]["hot"], 1)

        response = self.client.patch(
            f"/api/admin/photo-activities/{activity['id']}",
            headers=self._headers(self.admin_token),
            json={"hot": 50},
        )
        self.assertEqual(response.status_code, 422, response.text)

        response = self.client.post(
            "/api/admin/resources",
            headers=self._headers(self.admin_token),
            json={"title": "非法类型", "year": 2026, "category": "video", "resourceUrl": "x"},
        )
        self.assertEqual(response.status_code, 422, response.text)

        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'resource_categories'"
                )
                self.assertIsNone(cursor.fetchone())

    def test_01_schema_and_project_member_backfill(self) -> None:
        response = self.client.get("/api/projects/1")
        self.assertEqual(response.status_code, 200)
        members = response.json()["data"]["memberList"]
        self.assertEqual([member["name"] for member in members], ["李明", "王小雨", "Chen Alex"])
        self.assertEqual(members[0]["role"], "leader")
        self.assertFalse(members[0]["registered"])

        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA user_version")
                self.assertEqual(cursor.fetchone()["user_version"], 12)
                cursor.execute("PRAGMA table_info(conversation_members)")
                member_columns = {column["name"] for column in cursor.fetchall()}
                self.assertNotIn("request_status", member_columns)
                cursor.execute("PRAGMA table_info(comment_notifications)")
                notification_columns = {column["name"] for column in cursor.fetchall()}
                self.assertEqual(
                    notification_columns,
                    {
                        "id",
                        "kind",
                        "recipient_id",
                        "actor_id",
                        "comment_id",
                        "target_type",
                        "target_id",
                        "created_at",
                        "read_at",
                    },
                )
                cursor.execute("SELECT COUNT(*) AS total FROM comment_notifications")
                self.assertEqual(cursor.fetchone()["total"], 0)

        migration = (
            Path(__file__).parents[1] / "sql" / "migrations" / "006_unified_direct_messages.sql"
        ).read_text(encoding="utf-8")
        legacy = sqlite3.connect(":memory:")
        legacy.row_factory = sqlite3.Row
        legacy.execute("PRAGMA foreign_keys = ON")
        legacy.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY);
            CREATE TABLE conversations (id INTEGER PRIMARY KEY);
            CREATE TABLE conversation_members (
              conversation_id INTEGER NOT NULL,
              user_id INTEGER NOT NULL,
              request_status TEXT NOT NULL,
              last_read_message_id INTEGER,
              hidden_at TEXT,
              muted INTEGER NOT NULL DEFAULT 0,
              joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (conversation_id, user_id),
              FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX idx_conversation_members_user
              ON conversation_members(user_id, request_status, conversation_id);
            INSERT INTO users (id) VALUES (1), (2);
            INSERT INTO conversations (id) VALUES (1);
            INSERT INTO conversation_members
              (conversation_id, user_id, request_status, hidden_at)
            VALUES (1, 1, 'pending', NULL),
                   (1, 2, 'declined', '2026-08-01 00:00:00');
            PRAGMA user_version = 5;
            """
        )
        legacy.executescript(migration)
        self.assertEqual(legacy.execute("PRAGMA user_version").fetchone()[0], 6)
        migrated_columns = {
            column["name"] for column in legacy.execute("PRAGMA table_info(conversation_members)")
        }
        self.assertNotIn("request_status", migrated_columns)
        migrated_members = legacy.execute(
            "SELECT user_id, hidden_at FROM conversation_members ORDER BY user_id"
        ).fetchall()
        self.assertIsNone(migrated_members[0]["hidden_at"])
        self.assertEqual(migrated_members[1]["hidden_at"], "2026-08-01 00:00:00")
        legacy.close()

        notification_migration = (
            Path(__file__).parents[1] / "sql" / "migrations" / "007_comment_notifications.sql"
        ).read_text(encoding="utf-8")
        notification_legacy = sqlite3.connect(":memory:")
        notification_legacy.row_factory = sqlite3.Row
        notification_legacy.execute("PRAGMA foreign_keys = ON")
        notification_legacy.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY);
            CREATE TABLE comments (
              id INTEGER PRIMARY KEY,
              user_id INTEGER NOT NULL,
              target_type TEXT NOT NULL,
              target_id INTEGER NOT NULL,
              content TEXT NOT NULL
            );
            CREATE TABLE comment_likes (
              comment_id INTEGER NOT NULL,
              user_id INTEGER NOT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (comment_id, user_id)
            );
            INSERT INTO users (id) VALUES (1), (2);
            INSERT INTO comments (id, user_id, target_type, target_id, content)
            VALUES (1, 1, 'project', 1, '旧留言');
            INSERT INTO comment_likes (comment_id, user_id) VALUES (1, 2);
            PRAGMA user_version = 6;
            """
        )
        notification_legacy.executescript(notification_migration)
        self.assertEqual(notification_legacy.execute("PRAGMA user_version").fetchone()[0], 7)
        self.assertEqual(
            notification_legacy.execute("SELECT COUNT(*) FROM comment_notifications").fetchone()[0],
            0,
        )
        notification_legacy.close()

    def test_02_profile_follow_and_block(self) -> None:
        response = self.client.patch(
            "/api/users/me/profile",
            headers=self._headers(self.alice_token),
            json={
                "displayName": "Alice Chen",
                "bio": "CAS 科技爱好者",
                "messagingPermission": "everyone",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["bio"], "CAS 科技爱好者")

        response = self.client.post(
            f"/api/users/{self.bob['id']}/follow",
            headers=self._headers(self.alice_token),
        )
        self.assertEqual(response.status_code, 200, response.text)
        profile = self.client.get(
            f"/api/users/{self.bob['id']}",
            headers=self._headers(self.alice_token),
        ).json()["data"]
        self.assertTrue(profile["relationship"]["following"])

        response = self.client.post(
            f"/api/users/{self.charlie['id']}/block",
            headers=self._headers(self.alice_token),
        )
        self.assertEqual(response.status_code, 200)
        profile = self.client.get(
            f"/api/users/{self.charlie['id']}",
            headers=self._headers(self.alice_token),
        ).json()["data"]
        self.assertTrue(profile["relationship"]["blocked"])

    def test_03_only_admin_can_bind_project_members(self) -> None:
        project = self.client.get("/api/projects/1").json()["data"]
        person_id = project["memberList"][0]["personId"]

        removed_claim = self.client.post(
            f"/api/people/{person_id}/claims",
            headers=self._headers(self.alice_token),
            json={"note": "校园噪音地图负责人"},
        )
        self.assertEqual(removed_claim.status_code, 404, removed_claim.text)

        removed_standalone_binding = self.client.patch(
            f"/api/admin/people/{person_id}/binding",
            headers=self._headers(self.admin_token),
            json={"userId": self.alice["id"]},
        )
        self.assertEqual(removed_standalone_binding.status_code, 404, removed_standalone_binding.text)

        denied = self.client.patch(
            f"/api/admin/projects/1/members/{person_id}/binding",
            headers=self._headers(self.alice_token),
            json={"userId": self.alice["id"]},
        )
        self.assertEqual(denied.status_code, 403, denied.text)

        wrong_project = self.client.patch(
            f"/api/admin/projects/999999/members/{person_id}/binding",
            headers=self._headers(self.admin_token),
            json={"userId": self.alice["id"]},
        )
        self.assertEqual(wrong_project.status_code, 404, wrong_project.text)

        bound = self.client.patch(
            f"/api/admin/projects/1/members/{person_id}/binding",
            headers=self._headers(self.admin_token),
            json={"userId": self.alice["id"]},
        )
        self.assertEqual(bound.status_code, 200, bound.text)
        project = self.client.get("/api/projects/1").json()["data"]
        leader = project["memberList"][0]
        self.assertTrue(leader["registered"])
        self.assertEqual(leader["userId"], self.alice["id"])

    def test_04_unified_message_daily_limit_reply_read_recall_and_block(self) -> None:
        response = self.client.post(
            "/api/conversations",
            headers=self._headers(self.alice_token),
            json={"targetUserId": self.bob["id"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        conversation_id = response.json()["data"]["id"]
        self.assertNotIn("requestStatus", response.json()["data"])

        first = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(self.alice_token),
            json={"type": "text", "body": "你好，我想聊聊 CAS", "clientMessageId": "alice-first"},
        )
        self.assertEqual(first.status_code, 200, first.text)
        first_message_id = first.json()["data"]["id"]
        retry = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(self.alice_token),
            json={"type": "text", "body": "你好，我想聊聊 CAS", "clientMessageId": "alice-first"},
        )
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json()["data"]["id"], first_message_id)

        recalled = self.client.post(
            f"/api/messages/{first_message_id}/recall",
            headers=self._headers(self.alice_token),
        )
        self.assertEqual(recalled.status_code, 200, recalled.text)

        second = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(self.alice_token),
            json={"type": "text", "body": "第二条", "clientMessageId": "alice-second-same-day"},
        )
        self.assertEqual(second.status_code, 429, second.text)
        self.assertIn("每天最多发送一条", second.json()["detail"])

        # Recalled messages still consume quota, but a Beijing-calendar-day
        # rollover restores one allowance.
        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE messages SET created_at = datetime('now', '-1 day') WHERE id = %s",
                    (first_message_id,),
                )

        second = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(self.alice_token),
            json={"type": "text", "body": "新的一天", "clientMessageId": "alice-second-day"},
        )
        self.assertEqual(second.status_code, 200, second.text)
        second_message_id = second.json()["data"]["id"]

        third_before_reply = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(self.alice_token),
            json={"type": "text", "body": "当天再发", "clientMessageId": "alice-third-before-reply"},
        )
        self.assertEqual(third_before_reply.status_code, 429, third_before_reply.text)

        conversations = self.client.get(
            "/api/conversations",
            headers=self._headers(self.bob_token),
        )
        self.assertEqual(conversations.status_code, 200, conversations.text)
        conversation = next(item for item in conversations.json()["data"] if item["id"] == conversation_id)
        self.assertNotIn("requestStatus", conversation)

        history = self.client.get(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(self.bob_token),
        )
        self.assertEqual(history.status_code, 200, history.text)
        self.assertNotIn("requestStatus", history.json())
        self.assertTrue(history.json()["data"][0]["recalled"])

        replied = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(self.bob_token),
            json={"type": "text", "body": "可以聊", "clientMessageId": "bob-first-reply"},
        )
        self.assertEqual(replied.status_code, 200, replied.text)

        third = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(self.alice_token),
            json={"type": "text", "body": "收到回复后可继续", "clientMessageId": "alice-third"},
        )
        self.assertEqual(third.status_code, 200, third.text)

        followed = self.client.post(
            f"/api/users/{self.alice['id']}/follow",
            headers=self._headers(self.bob_token),
        )
        self.assertEqual(followed.status_code, 200, followed.text)
        unfollowed = self.client.delete(
            f"/api/users/{self.alice['id']}/follow",
            headers=self._headers(self.bob_token),
        )
        self.assertEqual(unfollowed.status_code, 200, unfollowed.text)
        fourth = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(self.alice_token),
            json={"type": "text", "body": "回复解锁不因取消关注失效", "clientMessageId": "alice-fourth"},
        )
        self.assertEqual(fourth.status_code, 200, fourth.text)
        last_message_id = fourth.json()["data"]["id"]

        counts = self.client.get(
            "/api/messages/unread-count",
            headers=self._headers(self.bob_token),
        ).json()
        self.assertEqual(counts["unread"], 3)
        self.assertNotIn("requests", counts)

        read = self.client.post(
            f"/api/conversations/{conversation_id}/read",
            headers=self._headers(self.bob_token),
            json={"messageId": last_message_id},
        )
        self.assertEqual(read.status_code, 200, read.text)
        counts = self.client.get(
            "/api/messages/unread-count",
            headers=self._headers(self.bob_token),
        ).json()
        self.assertEqual(counts["unread"], 0)

        report = self.client.post(
            f"/api/messages/{first_message_id}/reports",
            headers=self._headers(self.bob_token),
            json={"reason": "集成测试举报"},
        )
        self.assertEqual(report.status_code, 200, report.text)
        reports = self.client.get(
            "/api/admin/message-reports?status=pending",
            headers=self._headers(self.admin_token),
        )
        self.assertEqual(reports.status_code, 200, reports.text)
        report_id = reports.json()["data"][0]["id"]
        reviewed = self.client.patch(
            f"/api/admin/message-reports/{report_id}",
            headers=self._headers(self.admin_token),
            json={"status": "dismissed"},
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.text)

        blocked = self.client.post(
            f"/api/users/{self.alice['id']}/block",
            headers=self._headers(self.bob_token),
        )
        self.assertEqual(blocked.status_code, 200)
        denied = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(self.alice_token),
            json={"type": "text", "body": "这条不应发送成功"},
        )
        self.assertEqual(denied.status_code, 403)

    def test_05_follow_dynamically_unlocks_and_unfollow_restores_limit(self) -> None:
        opened = self.client.post(
            "/api/conversations",
            headers=self._headers(self.bob_token),
            json={"targetUserId": self.charlie["id"]},
        )
        self.assertEqual(opened.status_code, 200, opened.text)
        conversation_id = opened.json()["data"]["id"]
        first = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(self.bob_token),
            json={"type": "project", "body": "", "projectId": 1, "clientMessageId": "follow-limit-project"},
        )
        self.assertEqual(first.status_code, 200, first.text)

        recalled = self.client.post(
            f"/api/messages/{first.json()['data']['id']}/recall",
            headers=self._headers(self.bob_token),
        )
        self.assertEqual(recalled.status_code, 200, recalled.text)
        limited = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(self.bob_token),
            json={"type": "text", "body": "撤回后仍受限", "clientMessageId": "follow-limit-before-follow"},
        )
        self.assertEqual(limited.status_code, 429, limited.text)

        followed = self.client.post(
            f"/api/users/{self.bob['id']}/follow",
            headers=self._headers(self.charlie_token),
        )
        self.assertEqual(followed.status_code, 200, followed.text)
        unlocked = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(self.bob_token),
            json={"type": "text", "body": "关注后解锁", "clientMessageId": "follow-limit-unlocked"},
        )
        self.assertEqual(unlocked.status_code, 200, unlocked.text)

        unfollowed = self.client.delete(
            f"/api/users/{self.bob['id']}/follow",
            headers=self._headers(self.charlie_token),
        )
        self.assertEqual(unfollowed.status_code, 200, unfollowed.text)
        limited_again = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(self.bob_token),
            json={"type": "text", "body": "取消关注后恢复限制", "clientMessageId": "follow-limit-after-unfollow"},
        )
        self.assertEqual(limited_again.status_code, 429, limited_again.text)

    def test_05_messaging_permissions_still_control_new_conversations(self) -> None:
        sender = self._register("permission_sender", "Permission Sender")
        sender_token = self._login("permission_sender", "password123")

        everyone = self._register("permission_everyone", "Permission Everyone")
        everyone_opened = self.client.post(
            "/api/conversations",
            headers=self._headers(sender_token),
            json={"targetUserId": everyone["id"]},
        )
        self.assertEqual(everyone_opened.status_code, 200, everyone_opened.text)

        following = self._register("permission_following", "Permission Following")
        following_token = self._login("permission_following", "password123")
        updated = self.client.patch(
            "/api/users/me/profile",
            headers=self._headers(following_token),
            json={"messagingPermission": "following"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        denied = self.client.post(
            "/api/conversations",
            headers=self._headers(sender_token),
            json={"targetUserId": following["id"]},
        )
        self.assertEqual(denied.status_code, 403, denied.text)
        self.client.post(
            f"/api/users/{sender['id']}/follow",
            headers=self._headers(following_token),
        )
        allowed = self.client.post(
            "/api/conversations",
            headers=self._headers(sender_token),
            json={"targetUserId": following["id"]},
        )
        self.assertEqual(allowed.status_code, 200, allowed.text)

        mutual = self._register("permission_mutual", "Permission Mutual")
        mutual_token = self._login("permission_mutual", "password123")
        updated = self.client.patch(
            "/api/users/me/profile",
            headers=self._headers(mutual_token),
            json={"messagingPermission": "mutual"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.client.post(
            f"/api/users/{sender['id']}/follow",
            headers=self._headers(mutual_token),
        )
        denied = self.client.post(
            "/api/conversations",
            headers=self._headers(sender_token),
            json={"targetUserId": mutual["id"]},
        )
        self.assertEqual(denied.status_code, 403, denied.text)
        self.client.post(
            f"/api/users/{mutual['id']}/follow",
            headers=self._headers(sender_token),
        )
        allowed = self.client.post(
            "/api/conversations",
            headers=self._headers(sender_token),
            json={"targetUserId": mutual["id"]},
        )
        self.assertEqual(allowed.status_code, 200, allowed.text)

        nobody = self._register("permission_nobody", "Permission Nobody")
        nobody_token = self._login("permission_nobody", "password123")
        updated = self.client.patch(
            "/api/users/me/profile",
            headers=self._headers(nobody_token),
            json={"messagingPermission": "nobody"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        denied = self.client.post(
            "/api/conversations",
            headers=self._headers(sender_token),
            json={"targetUserId": nobody["id"]},
        )
        self.assertEqual(denied.status_code, 403, denied.text)

    def test_05_parallel_sends_cannot_bypass_daily_limit(self) -> None:
        sender = self._register("parallel_sender", "Parallel Sender")
        recipient = self._register("parallel_recipient", "Parallel Recipient")
        sender_token = self._login("parallel_sender", "password123")
        opened = self.client.post(
            "/api/conversations",
            headers=self._headers(sender_token),
            json={"targetUserId": recipient["id"]},
        )
        self.assertEqual(opened.status_code, 200, opened.text)
        conversation_id = opened.json()["data"]["id"]
        barrier = threading.Barrier(2)

        def send_parallel(client_message_id: str):
            barrier.wait()
            return self.client.post(
                f"/api/conversations/{conversation_id}/messages",
                headers=self._headers(sender_token),
                json={
                    "type": "text",
                    "body": client_message_id,
                    "clientMessageId": client_message_id,
                },
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(send_parallel, ("parallel-one", "parallel-two")))
        self.assertEqual(sorted(response.status_code for response in responses), [200, 429])

    def test_06_websocket_ticket_is_single_use(self) -> None:
        ticket = self.client.post(
            "/api/messages/stream-ticket",
            headers=self._headers(self.alice_token),
        ).json()["ticket"]
        with self.client.websocket_connect(f"/api/messages/ws?ticket={ticket}") as websocket:
            websocket.send_text("ping")
        with self.assertRaises(Exception):
            with self.client.websocket_connect(f"/api/messages/ws?ticket={ticket}"):
                pass

    def test_07_announcements_public_flow_and_admin_editing(self) -> None:
        public_list = self.client.get("/api/announcements?page=1&pageSize=2")
        self.assertEqual(public_list.status_code, 200, public_list.text)
        self.assertEqual(len(public_list.json()["data"]), 2)
        self.assertIsInstance(public_list.json()["data"][0], dict)
        self.assertIn("title", public_list.json()["data"][0])

        created = self.client.post(
            "/api/admin/announcements",
            headers=self._headers(self.admin_token),
            json={
                "title": "自动化测试公告",
                "summary": "先归档保存",
                "content": "第一段。\n\n第二段。",
                "status": "archived",
                "isPinned": False,
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        announcement_id = created.json()["data"]["id"]
        hidden = self.client.get(f"/api/announcements/{announcement_id}")
        self.assertEqual(hidden.status_code, 404)

        published = self.client.patch(
            f"/api/admin/announcements/{announcement_id}",
            headers=self._headers(self.admin_token),
            json={"status": "published", "isPinned": True, "summary": "现已发布"},
        )
        self.assertEqual(published.status_code, 200, published.text)
        detail = self.client.get(f"/api/announcements/{announcement_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["data"]["summary"], "现已发布")
        self.assertTrue(detail.json()["data"]["isPinned"])
        self.assertGreaterEqual(detail.json()["data"]["viewCount"], 1)

        rejected_draft = self.client.post(
            "/api/admin/announcements",
            headers=self._headers(self.admin_token),
            json={"title": "非法草稿", "content": "正文", "status": "draft"},
        )
        self.assertEqual(rejected_draft.status_code, 422)

        comment = self.client.post(
            "/api/comments",
            headers=self._headers(self.bob_token),
            json={"targetType": "announcement", "targetId": announcement_id, "content": "待删除留言"},
        )
        self.assertEqual(comment.status_code, 200, comment.text)
        reply = self.client.post(
            "/api/comments",
            headers=self._headers(self.charlie_token),
            json={
                "targetType": "announcement",
                "targetId": announcement_id,
                "content": "待删除回复",
                "parentId": comment.json()["data"]["id"],
            },
        )
        self.assertEqual(reply.status_code, 200, reply.text)
        deleted = self.client.delete(
            f"/api/admin/announcements/{announcement_id}",
            headers=self._headers(self.admin_token),
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(self.client.get(f"/api/announcements/{announcement_id}").status_code, 404)
        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) AS total FROM comments WHERE target_type = 'announcement' AND target_id = %s",
                    (announcement_id,),
                )
                self.assertEqual(cursor.fetchone()["total"], 0)
                cursor.execute(
                    "SELECT COUNT(*) AS total FROM comment_notifications WHERE target_type = 'announcement' AND target_id = %s",
                    (announcement_id,),
                )
                self.assertEqual(cursor.fetchone()["total"], 0)

    def test_08_project_resource_announcement_comment_threads(self) -> None:
        root = self.client.post(
            "/api/comments",
            headers=self._headers(self.bob_token),
            json={"targetType": "project", "targetId": 1, "content": "这个项目的思路不错"},
        )
        self.assertEqual(root.status_code, 200, root.text)
        root_id = root.json()["data"]["id"]

        reply = self.client.post(
            "/api/comments",
            headers=self._headers(self.charlie_token),
            json={
                "targetType": "project",
                "targetId": 1,
                "content": "我也想参与",
                "parentId": root_id,
            },
        )
        self.assertEqual(reply.status_code, 200, reply.text)
        reply_id = reply.json()["data"]["id"]
        nested_reply = self.client.post(
            "/api/comments",
            headers=self._headers(self.bob_token),
            json={
                "targetType": "project",
                "targetId": 1,
                "content": "欢迎，一起讨论",
                "parentId": reply_id,
            },
        )
        self.assertEqual(nested_reply.status_code, 200, nested_reply.text)

        resource_root = self.client.post(
            "/api/comments",
            headers=self._headers(self.alice_token),
            json={"targetType": "resource", "targetId": 1, "content": "资源很实用"},
        )
        self.assertEqual(resource_root.status_code, 200, resource_root.text)
        self_reply = self.client.post(
            "/api/comments",
            headers=self._headers(self.alice_token),
            json={
                "targetType": "resource",
                "targetId": 1,
                "content": "补充一下自己的留言",
                "parentId": resource_root.json()["data"]["id"],
            },
        )
        self.assertEqual(self_reply.status_code, 200, self_reply.text)
        self_like = self.client.post(
            f"/api/comments/{resource_root.json()['data']['id']}/like",
            headers=self._headers(self.alice_token),
        )
        self.assertEqual(self_like.status_code, 200, self_like.text)
        alice_replies = self.client.get(
            "/api/comment-notifications?kind=reply",
            headers=self._headers(self.alice_token),
        )
        self.assertEqual(alice_replies.status_code, 200, alice_replies.text)
        self.assertEqual(alice_replies.json()["total"], 0)
        alice_likes = self.client.get(
            "/api/comment-notifications?kind=like",
            headers=self._headers(self.alice_token),
        )
        self.assertEqual(alice_likes.json()["total"], 0)
        denied_reply = self.client.post(
            "/api/comments",
            headers=self._headers(self.charlie_token),
            json={
                "targetType": "resource",
                "targetId": 1,
                "content": "这条回复不应成功",
                "parentId": resource_root.json()["data"]["id"],
            },
        )
        self.assertEqual(denied_reply.status_code, 403)

        announcement_comment = self.client.post(
            "/api/comments",
            headers=self._headers(self.bob_token),
            json={"targetType": "announcement", "targetId": 1, "content": "收到公告"},
        )
        self.assertEqual(announcement_comment.status_code, 200, announcement_comment.text)

        liked = self.client.post(
            f"/api/comments/{root_id}/like",
            headers=self._headers(self.alice_token),
        )
        self.assertEqual(liked.status_code, 200, liked.text)
        thread = self.client.get(
            "/api/comments?targetType=project&targetId=1&sort=hot",
            headers=self._headers(self.alice_token),
        )
        self.assertEqual(thread.status_code, 200, thread.text)
        item = next(row for row in thread.json()["data"] if row["id"] == root_id)
        self.assertEqual(item["likeCount"], 1)
        self.assertTrue(item["liked"])
        self.assertEqual(len(item["replies"]), 2)
        self.assertEqual(item["replies"][1]["rootId"], root_id)

        reply_notifications = self.client.get(
            "/api/comment-notifications?kind=reply&page=1&pageSize=20",
            headers=self._headers(self.bob_token),
        )
        self.assertEqual(reply_notifications.status_code, 200, reply_notifications.text)
        reply_payload = reply_notifications.json()
        self.assertEqual(reply_payload["total"], 1)
        self.assertEqual(reply_payload["data"][0]["comment"]["id"], reply_id)
        self.assertEqual(reply_payload["data"][0]["actor"]["id"], self.charlie["id"])
        self.assertTrue(reply_payload["data"][0]["target"]["url"].endswith(f"#comment-{reply_id}"))

        like_notifications = self.client.get(
            "/api/comment-notifications?kind=like&page=1&pageSize=20",
            headers=self._headers(self.bob_token),
        )
        self.assertEqual(like_notifications.status_code, 200, like_notifications.text)
        like_payload = like_notifications.json()
        self.assertEqual(like_payload["total"], 1)
        like_notification_id = like_payload["data"][0]["id"]
        self.assertEqual(like_payload["data"][0]["comment"]["id"], root_id)

        context = self.client.get(
            f"/api/comments/{reply_id}/context",
            headers=self._headers(self.bob_token),
        )
        self.assertEqual(context.status_code, 200, context.text)
        self.assertEqual(context.json()["data"]["id"], root_id)
        self.assertEqual(context.json()["focusCommentId"], reply_id)

        counts = self.client.get(
            "/api/message-center/unread-count",
            headers=self._headers(self.bob_token),
        )
        self.assertEqual(counts.status_code, 200, counts.text)
        self.assertEqual(counts.json()["replies"], 1)
        self.assertEqual(counts.json()["likes"], 1)
        self.assertEqual(
            counts.json()["total"],
            counts.json()["messages"] + counts.json()["replies"] + counts.json()["likes"],
        )

        read_reply = self.client.post(
            "/api/comment-notifications/read",
            headers=self._headers(self.bob_token),
            json={"kind": "reply", "throughId": reply_payload["latestId"]},
        )
        self.assertEqual(read_reply.status_code, 200, read_reply.text)
        read_like = self.client.post(
            "/api/comment-notifications/read",
            headers=self._headers(self.bob_token),
            json={"kind": "like", "throughId": like_payload["latestId"]},
        )
        self.assertEqual(read_like.status_code, 200, read_like.text)

        duplicate_like = self.client.post(
            f"/api/comments/{root_id}/like",
            headers=self._headers(self.alice_token),
        )
        self.assertEqual(duplicate_like.status_code, 200, duplicate_like.text)
        counts = self.client.get(
            "/api/message-center/unread-count",
            headers=self._headers(self.bob_token),
        ).json()
        self.assertEqual(counts["likes"], 0)

        unliked = self.client.delete(
            f"/api/comments/{root_id}/like",
            headers=self._headers(self.alice_token),
        )
        self.assertEqual(unliked.status_code, 200, unliked.text)
        reliked = self.client.post(
            f"/api/comments/{root_id}/like",
            headers=self._headers(self.alice_token),
        )
        self.assertEqual(reliked.status_code, 200, reliked.text)
        relike_payload = self.client.get(
            "/api/comment-notifications?kind=like",
            headers=self._headers(self.bob_token),
        ).json()
        self.assertEqual(relike_payload["total"], 1)
        self.assertEqual(relike_payload["data"][0]["id"], like_notification_id)
        self.assertFalse(relike_payload["data"][0]["read"])

        reported = self.client.post(
            f"/api/comments/{reply_id}/reports",
            headers=self._headers(self.alice_token),
            json={"reason": "留言区集成测试举报"},
        )
        self.assertEqual(reported.status_code, 200, reported.text)
        reports = self.client.get(
            "/api/admin/comment-reports?status=pending",
            headers=self._headers(self.admin_token),
        )
        self.assertEqual(reports.status_code, 200, reports.text)
        report = next(row for row in reports.json()["data"] if row["commentId"] == reply_id)
        reviewed = self.client.patch(
            f"/api/admin/comment-reports/{report['id']}",
            headers=self._headers(self.admin_token),
            json={"status": "resolved", "hideComment": True},
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.text)

        hidden_reply_notification = self.client.get(
            "/api/comment-notifications?kind=reply",
            headers=self._headers(self.bob_token),
        ).json()["data"][0]
        self.assertFalse(hidden_reply_notification["comment"]["available"])
        self.assertIsNone(hidden_reply_notification["target"]["url"])
        hidden_context = self.client.get(f"/api/comments/{reply_id}/context")
        self.assertEqual(hidden_context.status_code, 404)

        deleted = self.client.delete(
            f"/api/comments/{root_id}",
            headers=self._headers(self.bob_token),
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        remaining = self.client.get("/api/comments?targetType=project&targetId=1&sort=latest")
        item = next(row for row in remaining.json()["data"] if row["id"] == root_id)
        self.assertEqual(item["status"], "deleted")
        self.assertEqual(item["content"], "")
        self.assertEqual(len(item["replies"]), 1)
        deleted_like_notification = self.client.get(
            "/api/comment-notifications?kind=like",
            headers=self._headers(self.bob_token),
        ).json()["data"][0]
        self.assertFalse(deleted_like_notification["comment"]["available"])
        self.assertIsNone(deleted_like_notification["target"]["url"])

    def test_09_admin_project_two_stage_creation_and_member_contacts(self) -> None:
        created = self.client.post(
            "/api/admin/projects",
            headers=self._headers(self.admin_token),
            json={
                "name": "分阶段管理测试",
                "category": "测试分类",
                "year": 2026,
                "assetDir": "/CAS/__test_project_assets__/",
                "description": "首次创建只录入基本信息。",
                "casCreativity": True,
                "casActivity": True,
                "casService": False,
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        project = created.json()
        project_id = project["id"]
        self.assertEqual(project["leader"], "")
        self.assertEqual(project["members"], "")
        self.assertEqual(project["media"], [])
        self.assertEqual(project["updates"], [])
        self.assertEqual(project["memberList"], [])
        self.assertEqual(project["assetDir"], "/CAS/__test_project_assets__/")
        self.assertEqual(project["icon"], "/CAS/__test_project_assets__/icon.png")

        created_without_icon = self.client.post(
            "/api/admin/projects",
            headers=self._headers(self.admin_token),
            json={
                "name": "无图标占位测试",
                "category": "测试分类",
                "year": 2026,
                "assetDir": "/CAS/__test_project_assets__/no-icon/",
                "description": "未上传图标时应返回空值，由前端显示首字母。",
                "casCreativity": False,
                "casActivity": True,
                "casService": False,
            },
        )
        self.assertEqual(created_without_icon.status_code, 200, created_without_icon.text)
        self.assertIsNone(created_without_icon.json()["icon"])

        rejected_legacy_members = self.client.post(
            "/api/admin/projects",
            headers=self._headers(self.admin_token),
            json={
                "name": "不应创建",
                "leader": "负责人",
                "members": "负责人, 成员",
                "category": "测试分类",
                "year": 2026,
                "description": "旧成员文本不再属于首次创建字段。",
            },
        )
        self.assertEqual(rejected_legacy_members.status_code, 422, rejected_legacy_members.text)

        pending_members = self.client.patch(
            f"/api/admin/projects/{project_id}/members",
            headers=self._headers(self.admin_token),
            json={
                "members": [
                    {
                        "name": "负责人甲",
                        "role": "member",
                        "contactType": "wechat",
                        "contactValue": "leader_wechat",
                    },
                    {
                        "name": "成员乙",
                        "role": "member",
                        "contactType": "email",
                        "contactValue": "member@example.com",
                    },
                ]
            },
        )
        self.assertEqual(pending_members.status_code, 200, pending_members.text)
        self.assertEqual(pending_members.json()["leader"], "")
        self.assertEqual([item["role"] for item in pending_members.json()["memberList"]], ["member", "member"])
        pending_ids = [item["personId"] for item in pending_members.json()["memberList"]]

        updated_members = self.client.patch(
            f"/api/admin/projects/{project_id}/members",
            headers=self._headers(self.admin_token),
            json={
                "members": [
                    {
                        "personId": pending_ids[0],
                        "name": "负责人甲",
                        "role": "leader",
                        "contactType": "wechat",
                        "contactValue": "leader_wechat",
                    },
                    {
                        "personId": pending_ids[1],
                        "name": "成员乙",
                        "role": "member",
                        "contactType": "email",
                        "contactValue": "member@example.com",
                    },
                ]
            },
        )
        self.assertEqual(updated_members.status_code, 200, updated_members.text)
        project = updated_members.json()
        leader_person_id = project["memberList"][0]["personId"]
        self.assertEqual(project["leader"], "负责人甲")
        self.assertEqual(project["members"], "负责人甲, 成员乙")
        self.assertEqual(
            [(item["name"], item["contactType"], item["contactValue"]) for item in project["memberList"]],
            [
                ("负责人甲", "wechat", "leader_wechat"),
                ("成员乙", "email", "member@example.com"),
            ],
        )

        invalid_leaders = self.client.patch(
            f"/api/admin/projects/{project_id}/members",
            headers=self._headers(self.admin_token),
            json={
                "members": [
                    {"personId": leader_person_id, "name": "负责人甲", "role": "leader"},
                    {"name": "成员乙", "role": "leader"},
                ]
            },
        )
        self.assertEqual(invalid_leaders.status_code, 422, invalid_leaders.text)

        missing_project = self.client.patch(
            "/api/admin/projects/999999/members",
            headers=self._headers(self.admin_token),
            json={"members": [{"name": "不存在的负责人", "role": "leader"}]},
        )
        self.assertEqual(missing_project.status_code, 404, missing_project.text)

        direct_leader_update = self.client.patch(
            f"/api/admin/projects/{project_id}",
            headers=self._headers(self.admin_token),
            json={"leader": "绕过成员管理的负责人"},
        )
        self.assertEqual(direct_leader_update.status_code, 422, direct_leader_update.text)

        updated_content = self.client.patch(
            f"/api/admin/projects/{project_id}",
            headers=self._headers(self.admin_token),
            json={
                "updates": [
                    {
                        "content": "项目创建后补充的第一条动态",
                        "images": ["activity-1.jpg", "activity-2.jpg"],
                    },
                    {"content": "没有照片的第二条动态", "images": []},
                ],
            },
        )
        self.assertEqual(updated_content.status_code, 200, updated_content.text)
        self.assertEqual(updated_content.json()["media"], [])
        first_update = updated_content.json()["updates"][0]
        self.assertRegex(first_update["id"], r"^[a-f0-9]{32}$")
        self.assertEqual(first_update["content"], "项目创建后补充的第一条动态")
        self.assertEqual(first_update["images"], ["activity-1.jpg", "activity-2.jpg"])

        rejected_project_media = self.client.patch(
            f"/api/admin/projects/{project_id}",
            headers=self._headers(self.admin_token),
            json={"media": ["/CAS/test/global-media.jpg"]},
        )
        self.assertEqual(rejected_project_media.status_code, 422, rejected_project_media.text)

        public_project = self.client.get(f"/api/projects/{project_id}")
        self.assertEqual(public_project.status_code, 200, public_project.text)
        public_members = public_project.json()["data"]["memberList"]
        self.assertEqual(public_members[0]["contactType"], "wechat")
        self.assertEqual(public_members[1]["contactValue"], "member@example.com")
        self.assertEqual(
            public_project.json()["data"]["updates"][0]["images"],
            [
                "/CAS/__test_project_assets__/activity-1.jpg",
                "/CAS/__test_project_assets__/activity-2.jpg",
            ],
        )

        missing_author = self.client.post(
            f"/api/admin/projects/{project_id}/updates",
            headers=self._headers(self.admin_token),
            data={"content": "后台不能直接以站内管理员身份发布", "images": "[]"},
        )
        self.assertEqual(missing_author.status_code, 422, missing_author.text)
        uploaded = self.client.post(
            f"/api/admin/projects/{project_id}/updates",
            headers=self._headers(self.admin_token),
            data={
                "content": "上传照片动态",
                "images": "[]",
                "authorPersonId": str(leader_person_id),
            },
            files=[("photos", ("现场照片.png", self.upload_photo, "image/png"))],
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        uploaded_update = next(
            item for item in uploaded.json()["updates"] if item["content"] == "上传照片动态"
        )
        update_id = uploaded_update["id"]
        self.assertEqual(uploaded.json()["updates"][0]["id"], update_id)
        self.assertEqual(uploaded_update["authorPersonId"], leader_person_id)
        self.assertNotIn("authorUserId", uploaded_update)
        self.assertEqual(uploaded_update["authorName"], "负责人甲")
        self.assertEqual(uploaded_update["authorRole"], "leader")
        self.assertEqual(uploaded_update["images"], [f"updates/{update_id}/现场照片.png"])
        uploaded_file = self.project_asset_dir / "updates" / update_id / "现场照片.png"
        self.assertTrue(uploaded_file.is_file())

        appended = self.client.patch(
            f"/api/admin/projects/{project_id}/updates/{update_id}",
            headers=self._headers(self.admin_token),
            data={"content": "上传照片动态（已编辑）", "images": json.dumps(uploaded_update["images"], ensure_ascii=False)},
            files=[("photos", ("现场照片.png", self.upload_photo, "image/png"))],
        )
        self.assertEqual(appended.status_code, 200, appended.text)
        appended_update = next(item for item in appended.json()["updates"] if item["id"] == update_id)
        self.assertEqual(
            appended_update["images"],
            [f"updates/{update_id}/现场照片.png", f"updates/{update_id}/现场照片-2.png"],
        )

        deleted = self.client.delete(
            f"/api/admin/projects/{project_id}/updates/{update_id}",
            headers=self._headers(self.admin_token),
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertFalse(uploaded_file.exists(), "删除动态应同时删除专属上传照片")
        self.assertFalse(uploaded_file.parent.exists())

        files_before_failed_upload = set((self.project_asset_dir / "updates").rglob("*"))
        with patch("backend.admin.MAX_PROJECT_PHOTO_BYTES", 4):
            too_large = self.client.post(
                f"/api/admin/projects/{project_id}/updates",
                headers=self._headers(self.admin_token),
                data={
                    "content": "应回滚",
                    "images": "[]",
                    "authorPersonId": str(leader_person_id),
                },
                files=[("photos", ("too-large.png", self.upload_photo, "image/png"))],
            )
        self.assertEqual(too_large.status_code, 413, too_large.text)
        self.assertEqual(set((self.project_asset_dir / "updates").rglob("*")), files_before_failed_upload)

    def test_10_admin_json_import_export(self) -> None:
        document = {
            "format": "nethub-campus-wiki-data",
            "version": 2,
            "projects": [
                {
                    "name": "JSON 导入 CAS",
                    "category": "导入测试",
                    "year": 2026,
                    "assetDir": "/CAS/__test_project_assets__/",
                    "description": "通过统一 JSON 导入的测试项目。",
                    "cas": {"creativity": True, "activity": False, "service": True},
                    "popularity": 17,
                    "members": [
                        {
                            "name": "负责人甲",
                            "role": "leader",
                            "contactType": "wechat",
                            "contactValue": "json_leader",
                        },
                        {"name": "成员乙", "role": "member", "contactType": None, "contactValue": None},
                    ],
                    "updates": [
                        {
                            "id": "abcdef0123456789abcdef0123456789",
                            "content": "第一条导入动态",
                            "images": ["activity-1.jpg"],
                        }
                    ],
                }
            ],
            "resources": [
                {
                    "title": "JSON 导入资源",
                    "description": "普通资源导入测试。",
                    "year": 2026,
                    "category": "other",
                    "label": "会被规范化",
                    "hot": 8,
                    "downloads": 9,
                    "image": "https://example.com/resource-cover.png",
                    "resourceUrl": "https://example.com/resource.pdf",
                }
            ],
            "photoActivities": [
                {
                    "activity": "JSON 导入照片活动",
                    "description": "照片活动导入测试。",
                    "year": 2026,
                    "hot": 6,
                    "downloads": 7,
                    "sortOrder": 30,
                    "photoDir": None,
                    "photos": [
                        {
                            "title": "测试照片",
                            "src": "https://example.com/photo.jpg",
                            "sortOrder": 10,
                        }
                    ],
                }
            ],
        }
        preview = self.client.post(
            "/api/admin/data-import/preview",
            headers=self._headers(self.admin_token),
            json=document,
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(
            preview.json()["summary"],
            {
                "projects": 1,
                "members": 2,
                "updates": 1,
                "resources": 1,
                "photoActivities": 1,
                "photos": 1,
            },
        )
        self.assertEqual(preview.json()["warnings"], [])

        legacy_project_document = {
            "format": "nethub-campus-wiki-data",
            "version": 1,
            "projects": [{
                **document["projects"][0],
                "icon": "/CAS/__test_project_assets__/icon.png",
                "updates": [{
                    "content": "v1 动态",
                    "images": ["/CAS/__test_project_assets__/activity-1.jpg"],
                }],
            }],
            "resources": [],
            "photoActivities": [],
        }
        legacy_project_document["projects"][0].pop("assetDir", None)
        legacy_preview = self.client.post(
            "/api/admin/data-import/preview",
            headers=self._headers(self.admin_token),
            json=legacy_project_document,
        )
        self.assertEqual(legacy_preview.status_code, 200, legacy_preview.text)
        self.assertTrue(any("推断" in item["message"] for item in legacy_preview.json()["warnings"]))

        unconvertible_v1 = json.loads(json.dumps(legacy_project_document, ensure_ascii=False))
        unconvertible_v1["projects"][0]["icon"] = "https://example.com/icon.png"
        unconvertible_v1["projects"][0]["updates"][0]["images"] = ["https://example.com/photo.png"]
        rejected_v1 = self.client.post(
            "/api/admin/data-import/preview",
            headers=self._headers(self.admin_token),
            json=unconvertible_v1,
        )
        self.assertEqual(rejected_v1.status_code, 422, rejected_v1.text)
        self.assertIn("assetDir", rejected_v1.text)

        first_import = self.client.post(
            "/api/admin/data-import",
            headers=self._headers(self.admin_token),
            json=document,
        )
        self.assertEqual(first_import.status_code, 200, first_import.text)
        first_created = first_import.json()["created"]
        project_id = first_created["projects"][0]["id"]
        resource_id = first_created["resources"][0]["id"]
        activity_id = first_created["photoActivities"][0]["id"]

        second_import = self.client.post(
            "/api/admin/data-import",
            headers=self._headers(self.admin_token),
            json=document,
        )
        self.assertEqual(second_import.status_code, 200, second_import.text)
        second_created = second_import.json()["created"]
        self.assertNotEqual(project_id, second_created["projects"][0]["id"])
        self.assertNotEqual(resource_id, second_created["resources"][0]["id"])
        self.assertNotEqual(activity_id, second_created["photoActivities"][0]["id"])

        project_export = self.client.get(
            f"/api/admin/projects/{project_id}/export",
            headers=self._headers(self.admin_token),
        )
        self.assertEqual(project_export.status_code, 200, project_export.text)
        self.assertIn("attachment", project_export.headers["content-disposition"])
        exported_project = project_export.json()
        self.assertEqual(len(exported_project["projects"]), 1)
        self.assertEqual(exported_project["resources"], [])
        self.assertEqual(exported_project["projects"][0]["popularity"], 17)
        self.assertEqual(exported_project["projects"][0]["members"][0]["contactValue"], "json_leader")
        self.assertNotIn("id", exported_project["projects"][0])

        resource_export = self.client.get(
            f"/api/admin/resources/{resource_id}/export",
            headers=self._headers(self.admin_token),
        )
        self.assertEqual(resource_export.status_code, 200, resource_export.text)
        self.assertEqual(resource_export.json()["resources"][0]["label"], "其他资源")
        self.assertEqual(resource_export.json()["resources"][0]["hot"], 8)

        activity_export = self.client.get(
            f"/api/admin/photo-activities/{activity_id}/export",
            headers=self._headers(self.admin_token),
        )
        self.assertEqual(activity_export.status_code, 200, activity_export.text)
        self.assertEqual(activity_export.json()["photoActivities"][0]["photos"][0]["title"], "测试照片")

        all_export = self.client.get(
            "/api/admin/data-export",
            headers=self._headers(self.admin_token),
        )
        self.assertEqual(all_export.status_code, 200, all_export.text)
        self.assertEqual(all_export.json()["format"], "nethub-campus-wiki-data")
        self.assertGreaterEqual(len(all_export.json()["projects"]), 2)
        self.assertGreaterEqual(len(all_export.json()["resources"]), 2)
        self.assertGreaterEqual(len(all_export.json()["photoActivities"]), 2)

        warning_document = {
            "format": "nethub-campus-wiki-data",
            "version": 1,
            "projects": [],
            "resources": [
                {
                    "title": "缺失路径资源",
                    "description": "用于验证路径预警。",
                    "year": 2026,
                    "category": "other",
                    "label": "其他资源",
                    "hot": 0,
                    "downloads": 0,
                    "image": "/uploads/json-import/missing-cover.png",
                    "resourceUrl": "/uploads/json-import/missing-resource.pdf",
                }
            ],
            "photoActivities": [],
        }
        warning_preview = self.client.post(
            "/api/admin/data-import/preview",
            headers=self._headers(self.admin_token),
            json=warning_document,
        )
        self.assertEqual(warning_preview.status_code, 200, warning_preview.text)
        self.assertEqual(len(warning_preview.json()["warnings"]), 2)
        refused = self.client.post(
            "/api/admin/data-import",
            headers=self._headers(self.admin_token),
            json=warning_document,
        )
        self.assertEqual(refused.status_code, 409, refused.text)
        confirmed = self.client.post(
            "/api/admin/data-import?confirmWarnings=true",
            headers=self._headers(self.admin_token),
            json=warning_document,
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS total FROM projects")
                projects_before_invalid = cursor.fetchone()["total"]
        invalid_document = {
            **document,
            "projects": [document["projects"][0], {"name": "字段不完整"}],
            "resources": [],
            "photoActivities": [],
        }
        invalid = self.client.post(
            "/api/admin/data-import?confirmWarnings=true",
            headers=self._headers(self.admin_token),
            json=invalid_document,
        )
        self.assertEqual(invalid.status_code, 422, invalid.text)
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS total FROM projects")
                self.assertEqual(cursor.fetchone()["total"], projects_before_invalid)

        external_directory_document = {
            **document,
            "projects": [],
            "resources": [],
            "photoActivities": [
                {
                    **document["photoActivities"][0],
                    "photoDir": "https://example.com/photos/",
                    "photos": [],
                }
            ],
        }
        external_directory = self.client.post(
            "/api/admin/data-import/preview",
            headers=self._headers(self.admin_token),
            json=external_directory_document,
        )
        self.assertEqual(external_directory.status_code, 422, external_directory.text)
        self.assertIn("public", external_directory.text)

        template = self.client.get(
            "/api/admin/data-template",
            headers=self._headers(self.admin_token),
        )
        self.assertEqual(template.status_code, 200, template.text)
        self.assertEqual(template.json()["version"], 2)
        self.assertIn("assetDir", template.json()["projects"][0])
        self.assertNotIn("icon", template.json()["projects"][0])

    def test_11_cas_popularity_tracks_public_detail_views(self) -> None:
        clear_tracked_views()
        baseline = self.client.get("/api/projects/1?track=false").json()["data"]["popularity"]

        first = self.client.get(
            "/api/projects/1",
            headers=self._headers(self.alice_token),
        )
        second = self.client.get(
            "/api/projects/1",
            headers=self._headers(self.alice_token),
        )
        other_user = self.client.get(
            "/api/projects/1",
            headers=self._headers(self.bob_token),
        )
        guest_one = self.client.get("/api/projects/1")
        guest_two = self.client.get("/api/projects/1")
        untracked = self.client.get("/api/projects/1?track=false")

        self.assertEqual(first.json()["data"]["popularity"], baseline + 1)
        self.assertEqual(second.json()["data"]["popularity"], baseline + 1)
        self.assertEqual(other_user.json()["data"]["popularity"], baseline + 2)
        self.assertEqual(guest_one.json()["data"]["popularity"], baseline + 3)
        self.assertEqual(guest_two.json()["data"]["popularity"], baseline + 4)
        self.assertEqual(untracked.json()["data"]["popularity"], baseline + 4)
        self.assertEqual(self.client.get("/api/projects/999999").status_code, 404)
        rejected = self.client.patch(
            "/api/admin/projects/1",
            headers=self._headers(self.admin_token),
            json={"popularity": 999},
        )
        self.assertEqual(rejected.status_code, 422)

    def test_12_avatar_upload_replacement_and_removal(self) -> None:
        user = self._register("avatar_user", "Avatar User")
        token = self._login("avatar_user", "password123")
        with tempfile.TemporaryDirectory() as temp_dir:
            avatar_root = Path(temp_dir) / "avatars"
            with patch("backend.avatars.AVATAR_ROOT", avatar_root):
                image_buffer = io.BytesIO()
                Image.new("RGB", (800, 400), "orange").save(image_buffer, format="PNG")
                uploaded = self.client.post(
                    "/api/users/me/avatar",
                    headers=self._headers(token),
                    files={"avatar": ("wide.png", image_buffer.getvalue(), "image/png")},
                )
                self.assertEqual(uploaded.status_code, 200, uploaded.text)
                first_url = uploaded.json()["avatarUrl"]
                first_path = avatar_root / first_url.removeprefix("/uploads/avatars/")
                self.assertTrue(first_path.is_file())
                with Image.open(first_path) as stored:
                    self.assertEqual(stored.format, "WEBP")
                    self.assertEqual(stored.size, (512, 512))

                replacement_buffer = io.BytesIO()
                Image.new("RGB", (300, 900), "purple").save(replacement_buffer, format="JPEG")
                replaced = self.client.post(
                    "/api/users/me/avatar",
                    headers=self._headers(token),
                    files={"avatar": ("tall.jpg", replacement_buffer.getvalue(), "image/jpeg")},
                )
                self.assertEqual(replaced.status_code, 200, replaced.text)
                self.assertNotEqual(replaced.json()["avatarUrl"], first_url)
                self.assertFalse(first_path.exists())

                invalid = self.client.post(
                    "/api/users/me/avatar",
                    headers=self._headers(token),
                    files={"avatar": ("fake.png", b"not-an-image", "image/png")},
                )
                self.assertEqual(invalid.status_code, 422)

                oversized = self.client.post(
                    "/api/users/me/avatar",
                    headers=self._headers(token),
                    files={"avatar": ("large.png", b"x" * (5 * 1024 * 1024 + 1), "image/png")},
                )
                self.assertEqual(oversized.status_code, 413)

                removed = self.client.delete(
                    "/api/users/me/avatar",
                    headers=self._headers(token),
                )
                self.assertEqual(removed.status_code, 200, removed.text)
                self.assertIsNone(removed.json()["avatarUrl"])
                self.assertEqual(list(avatar_root.rglob("*.webp")), [])

        self.assertEqual(user["id"], uploaded.json()["id"])

    def test_13_admin_user_deletion_anonymizes_history(self) -> None:
        doomed = self._register("delete_me_user", "Delete Me")
        survivor = self._register("delete_survivor", "Survivor")
        doomed_token = self._login("delete_me_user", "password123")
        survivor_token = self._login("delete_survivor", "password123")

        followed = self.client.post(
            f"/api/users/{survivor['id']}/follow",
            headers=self._headers(doomed_token),
        )
        self.assertEqual(followed.status_code, 200, followed.text)
        conversation = self.client.post(
            "/api/conversations",
            headers=self._headers(survivor_token),
            json={"targetUserId": doomed["id"]},
        )
        self.assertEqual(conversation.status_code, 200, conversation.text)
        conversation_id = conversation.json()["data"]["id"]
        sent = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(doomed_token),
            json={"type": "text", "body": "需要匿名保留的私信"},
        )
        self.assertEqual(sent.status_code, 200, sent.text)
        comment = self.client.post(
            "/api/comments",
            headers=self._headers(doomed_token),
            json={"targetType": "project", "targetId": 1, "content": "需要匿名保留的留言"},
        )
        self.assertEqual(comment.status_code, 200, comment.text)
        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO people (display_name, user_id, source_key, status)
                    VALUES (%s, %s, %s, 'claimed')
                    """,
                    ("Delete Me", doomed["id"], f"delete-test:{doomed['id']}"),
                )
                person_id = cursor.lastrowid
                cursor.execute(
                    """
                    INSERT INTO project_members
                      (project_id, person_id, role, display_name_snapshot, sort_order)
                    VALUES (1, %s, 'member', 'Delete Me', 999)
                    """,
                    (person_id,),
                )
                cursor.execute(
                    "UPDATE users SET campus_verified = 1 WHERE id = %s",
                    (doomed["id"],),
                )

        deleted = self.client.delete(
            f"/api/admin/users/{doomed['id']}",
            headers=self._headers(self.admin_token),
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(
            self.client.get("/api/auth/me", headers=self._headers(doomed_token)).status_code,
            403,
        )
        users = self.client.get(
            "/api/admin/users",
            headers=self._headers(self.admin_token),
        ).json()["data"]
        self.assertNotIn(doomed["id"], [item["id"] for item in users])

        thread = self.client.get("/api/comments?targetType=project&targetId=1").json()["data"]
        retained_comment = next(item for item in thread if item["id"] == comment.json()["data"]["id"])
        self.assertEqual(retained_comment["content"], "需要匿名保留的留言")
        self.assertTrue(retained_comment["author"]["deleted"])
        self.assertEqual(retained_comment["author"]["displayName"], "已注销用户")
        self.assertIsNone(retained_comment["author"]["username"])

        conversations = self.client.get(
            "/api/conversations",
            headers=self._headers(survivor_token),
        ).json()["data"]
        retained_conversation = next(item for item in conversations if item["id"] == conversation_id)
        self.assertTrue(retained_conversation["otherUser"]["deleted"])
        messages = self.client.get(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(survivor_token),
        ).json()["data"]
        self.assertEqual(messages[-1]["body"], "需要匿名保留的私信")
        self.assertTrue(messages[-1]["sender"]["deleted"])
        refused = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(survivor_token),
            json={"type": "text", "body": "不应发送成功"},
        )
        self.assertEqual(refused.status_code, 409)

        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE id = %s", (doomed["id"],))
                deleted_row = cursor.fetchone()
                self.assertIsNotNone(deleted_row["deleted_at"])
                self.assertEqual(deleted_row["is_active"], 0)
                self.assertIsNone(deleted_row["avatar_url"])
                cursor.execute("SELECT user_id, status FROM people WHERE id = %s", (person_id,))
                person = cursor.fetchone()
                self.assertIsNone(person["user_id"])
                self.assertEqual(person["status"], "provisional")
                cursor.execute(
                    "SELECT COUNT(*) AS total FROM user_follows WHERE follower_id = %s OR following_id = %s",
                    (doomed["id"], doomed["id"]),
                )
                self.assertEqual(cursor.fetchone()["total"], 0)

        cannot_delete_self = self.client.delete(
            f"/api/admin/users/{self.client.get('/api/auth/me', headers=self._headers(self.admin_token)).json()['id']}",
            headers=self._headers(self.admin_token),
        )
        self.assertEqual(cannot_delete_self.status_code, 409)

    def test_14_report_center_locates_and_deletes_reported_content(self) -> None:
        sender = self._register("report_center_sender", "举报测试发送者")
        reporter = self._register("report_center_reporter", "举报测试接收者")
        sender_token = self._login("report_center_sender", "password123")
        reporter_token = self._login("report_center_reporter", "password123")

        conversation = self.client.post(
            "/api/conversations",
            headers=self._headers(sender_token),
            json={"targetUserId": reporter["id"]},
        )
        self.assertEqual(conversation.status_code, 200, conversation.text)
        conversation_id = conversation.json()["data"]["id"]
        sent = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(sender_token),
            json={"type": "text", "body": "需要由举报中心删除的私信"},
        )
        self.assertEqual(sent.status_code, 200, sent.text)
        message_id = sent.json()["data"]["id"]
        reported_message = self.client.post(
            f"/api/messages/{message_id}/reports",
            headers=self._headers(reporter_token),
            json={"reason": "举报中心定位测试"},
        )
        self.assertEqual(reported_message.status_code, 200, reported_message.text)
        pending_messages = self.client.get(
            "/api/admin/message-reports?status=pending",
            headers=self._headers(self.admin_token),
        ).json()["data"]
        message_report = next(row for row in pending_messages if row["messageId"] == message_id)

        context = self.client.get(
            f"/api/admin/message-reports/{message_report['id']}/context",
            headers=self._headers(self.admin_token),
        )
        self.assertEqual(context.status_code, 200, context.text)
        focused = next(row for row in context.json()["data"]["messages"] if row["reported"])
        self.assertEqual(focused["id"], message_id)
        self.assertEqual(focused["body"], "需要由举报中心删除的私信")

        deleted_message = self.client.delete(
            f"/api/admin/message-reports/{message_report['id']}/content",
            headers=self._headers(self.admin_token),
        )
        self.assertEqual(deleted_message.status_code, 200, deleted_message.text)
        history = self.client.get(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(reporter_token),
        ).json()["data"]
        removed_message = next(row for row in history if row["id"] == message_id)
        self.assertTrue(removed_message["recalled"])
        self.assertEqual(removed_message["body"], "")
        self.assertEqual(
            self.client.delete(
                f"/api/admin/message-reports/{message_report['id']}/content",
                headers=self._headers(self.admin_token),
            ).status_code,
            404,
        )

        comment = self.client.post(
            "/api/comments",
            headers=self._headers(sender_token),
            json={"targetType": "project", "targetId": 1, "content": "需要由举报中心删除的留言"},
        )
        self.assertEqual(comment.status_code, 200, comment.text)
        comment_id = comment.json()["data"]["id"]
        reported_comment = self.client.post(
            f"/api/comments/{comment_id}/reports",
            headers=self._headers(reporter_token),
            json={"reason": "举报中心删除测试"},
        )
        self.assertEqual(reported_comment.status_code, 200, reported_comment.text)
        pending_comments = self.client.get(
            "/api/admin/comment-reports?status=pending",
            headers=self._headers(self.admin_token),
        ).json()["data"]
        comment_report = next(row for row in pending_comments if row["commentId"] == comment_id)
        deleted_comment = self.client.delete(
            f"/api/admin/comment-reports/{comment_report['id']}/content",
            headers=self._headers(self.admin_token),
        )
        self.assertEqual(deleted_comment.status_code, 200, deleted_comment.text)
        comments = self.client.get("/api/comments?targetType=project&targetId=1").json()["data"]
        removed_comment = next(row for row in comments if row["id"] == comment_id)
        self.assertEqual(removed_comment["status"], "deleted")
        self.assertEqual(removed_comment["content"], "")
        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT content FROM comments WHERE id = %s", (comment_id,))
                self.assertEqual(cursor.fetchone()["content"], "")

    def test_15_bound_project_members_can_publish_updates(self) -> None:
        publisher = self._register("project_update_publisher", "Project Publisher")
        publisher_token = self._login("project_update_publisher", "password123")
        regular_member = self._register("project_update_member", "Project Update Member")
        regular_member_token = self._login("project_update_member", "password123")
        project = self.client.post(
            "/api/admin/projects",
            headers=self._headers(self.admin_token),
            json={
                "name": "成员发布动态测试",
                "category": "测试分类",
                "year": 2026,
                "assetDir": "/CAS/__test_project_assets__/",
                "description": "验证只有已绑定的项目成员可以发布。",
                "casCreativity": True,
                "casActivity": False,
                "casService": True,
            },
        )
        self.assertEqual(project.status_code, 200, project.text)
        project_id = project.json()["id"]
        members = self.client.patch(
            f"/api/admin/projects/{project_id}/members",
            headers=self._headers(self.admin_token),
            json={
                "members": [
                    {"name": "已绑定发布者", "role": "leader"},
                    {"name": "普通项目成员", "role": "member"},
                ]
            },
        )
        self.assertEqual(members.status_code, 200, members.text)
        person_ids = {
            member["name"]: member["personId"]
            for member in members.json()["memberList"]
        }
        binding = self.client.patch(
            f"/api/admin/projects/{project_id}/members/{person_ids['已绑定发布者']}/binding",
            headers=self._headers(self.admin_token),
            json={"userId": publisher["id"]},
        )
        self.assertEqual(binding.status_code, 200, binding.text)
        regular_binding = self.client.patch(
            f"/api/admin/projects/{project_id}/members/{person_ids['普通项目成员']}/binding",
            headers=self._headers(self.admin_token),
            json={"userId": regular_member["id"]},
        )
        self.assertEqual(regular_binding.status_code, 200, regular_binding.text)

        guest_detail = self.client.get(f"/api/projects/{project_id}?track=false")
        member_detail = self.client.get(
            f"/api/projects/{project_id}?track=false",
            headers=self._headers(publisher_token),
        )
        outsider_detail = self.client.get(
            f"/api/projects/{project_id}?track=false",
            headers=self._headers(self.bob_token),
        )
        self.assertFalse(guest_detail.json()["data"]["viewerPermissions"]["canCreateUpdate"])
        self.assertTrue(member_detail.json()["data"]["viewerPermissions"]["canCreateUpdate"])
        self.assertFalse(outsider_detail.json()["data"]["viewerPermissions"]["canCreateUpdate"])

        unauthenticated = self.client.post(
            f"/api/projects/{project_id}/updates",
            data={"content": "未登录不应发布"},
        )
        self.assertEqual(unauthenticated.status_code, 401)
        outsider = self.client.post(
            f"/api/projects/{project_id}/updates",
            headers=self._headers(self.bob_token),
            data={"content": "其他用户不应发布"},
        )
        self.assertEqual(outsider.status_code, 403)

        published = self.client.post(
            f"/api/projects/{project_id}/updates",
            headers=self._headers(publisher_token),
            data={"content": "成员发布的图文动态"},
            files=[("photos", ("成员照片.png", self.upload_photo, "image/png"))],
        )
        self.assertEqual(published.status_code, 200, published.text)
        update = next(
            item
            for item in published.json()["data"]["updates"]
            if item["content"] == "成员发布的图文动态"
        )
        self.assertRegex(update["id"], r"^[a-f0-9]{32}$")
        self.assertEqual(update["authorPersonId"], person_ids["已绑定发布者"])
        self.assertIsNone(update["authorUserId"])
        self.assertEqual(update["authorName"], "已绑定发布者")
        self.assertEqual(update["authorRole"], "leader")
        self.assertIsNotNone(update["createdAt"])
        self.assertEqual(
            update["images"],
            [f"/CAS/__test_project_assets__/updates/{update['id']}/成员照片.png"],
        )
        leader_update_file = (
            self.project_asset_dir / "updates" / update["id"] / "成员照片.png"
        )
        self.assertTrue(leader_update_file.is_file())

        regular_view = self.client.get(
            f"/api/projects/{project_id}?track=false",
            headers=self._headers(regular_member_token),
        ).json()["data"]
        leader_update_for_regular = next(
            item for item in regular_view["updates"] if item["id"] == update["id"]
        )
        self.assertFalse(leader_update_for_regular["canDelete"])
        self.assertTrue(update["canDelete"])
        self.assertEqual(
            self.client.delete(f"/api/projects/{project_id}/updates/{update['id']}").status_code,
            401,
        )
        self.assertEqual(
            self.client.delete(
                f"/api/projects/{project_id}/updates/{update['id']}",
                headers=self._headers(self.bob_token),
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.delete(
                f"/api/projects/{project_id}/updates/{update['id']}",
                headers=self._headers(regular_member_token),
            ).status_code,
            403,
        )

        regular_published = self.client.post(
            f"/api/projects/{project_id}/updates",
            headers=self._headers(regular_member_token),
            data={"content": "普通成员的多图动态"},
            files=[
                ("photos", ("多图-1.png", self.upload_photo, "image/png")),
                ("photos", ("多图-2.png", self.upload_photo, "image/png")),
            ],
        )
        self.assertEqual(regular_published.status_code, 200, regular_published.text)
        regular_update = next(
            item
            for item in regular_published.json()["data"]["updates"]
            if item["content"] == "普通成员的多图动态"
        )
        self.assertEqual(regular_published.json()["data"]["updates"][0]["id"], regular_update["id"])
        self.assertTrue(regular_update["canDelete"])
        regular_update_dir = self.project_asset_dir / "updates" / regular_update["id"]
        self.assertEqual(
            {path.name for path in regular_update_dir.iterdir()},
            {"多图-1.png", "多图-2.png"},
        )
        regular_deleted = self.client.delete(
            f"/api/projects/{project_id}/updates/{regular_update['id']}",
            headers=self._headers(regular_member_token),
        )
        self.assertEqual(regular_deleted.status_code, 200, regular_deleted.text)
        self.assertFalse(regular_update_dir.exists())
        self.assertNotIn(
            regular_update["id"],
            {item["id"] for item in regular_deleted.json()["data"]["updates"]},
        )
        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT updates FROM projects WHERE id = %s", (project_id,))
                stored_update_ids = {
                    item["id"] for item in json.loads(cursor.fetchone()["updates"])
                }
        self.assertNotIn(regular_update["id"], stored_update_ids)
        exported = self.client.get(
            f"/api/admin/projects/{project_id}/export",
            headers=self._headers(self.admin_token),
        )
        self.assertEqual(exported.status_code, 200, exported.text)
        exported_update = next(
            item
            for item in exported.json()["projects"][0]["updates"]
            if item["content"] == "成员发布的图文动态"
        )
        self.assertEqual(exported_update["authorName"], "已绑定发布者")
        self.assertNotIn("authorPersonId", exported_update)
        self.assertNotIn("authorUserId", exported_update)

        leader_deleted = self.client.delete(
            f"/api/projects/{project_id}/updates/{update['id']}",
            headers=self._headers(publisher_token),
        )
        self.assertEqual(leader_deleted.status_code, 200, leader_deleted.text)
        self.assertFalse(leader_update_file.parent.exists())
        self.assertNotIn(
            update["id"],
            {item["id"] for item in leader_deleted.json()["data"]["updates"]},
        )

        empty = self.client.post(
            f"/api/projects/{project_id}/updates",
            headers=self._headers(publisher_token),
            data={"content": ""},
        )
        self.assertEqual(empty.status_code, 422)
        too_long = self.client.post(
            f"/api/projects/{project_id}/updates",
            headers=self._headers(publisher_token),
            data={"content": "x" * 2001},
        )
        self.assertEqual(too_long.status_code, 422)
        too_many = self.client.post(
            f"/api/projects/{project_id}/updates",
            headers=self._headers(publisher_token),
            data={"content": "照片过多"},
            files=[
                ("photos", (f"photo-{index}.png", self.upload_photo, "image/png"))
                for index in range(10)
            ],
        )
        self.assertEqual(too_many.status_code, 422)
        oversized = self.client.post(
            f"/api/projects/{project_id}/updates",
            headers=self._headers(publisher_token),
            data={"content": "超大照片不应保存"},
            files=[("photos", ("oversized.png", b"x" * (5 * 1024 * 1024 + 1), "image/png"))],
        )
        self.assertEqual(oversized.status_code, 413)

        def publish_concurrently(sequence: int) -> int:
            response = self.client.post(
                f"/api/projects/{project_id}/updates",
                headers=self._headers(publisher_token),
                data={"content": f"并发动态 {sequence}"},
            )
            return response.status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(publish_concurrently, (1, 2)))
        self.assertEqual(statuses, [200, 200])
        final_updates = self.client.get(f"/api/projects/{project_id}?track=false").json()["data"]["updates"]
        final_contents = {item["content"] for item in final_updates}
        self.assertIn("并发动态 1", final_contents)
        self.assertIn("并发动态 2", final_contents)


if __name__ == "__main__":
    unittest.main()
