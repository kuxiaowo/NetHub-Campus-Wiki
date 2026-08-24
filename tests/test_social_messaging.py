"""用户、人员认领和私信主流程集成测试。"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

_TEMP_DIR = tempfile.TemporaryDirectory()
os.environ["DATABASE_PATH"] = str(Path(_TEMP_DIR.name) / "campus_wiki_test.db")
os.environ["AUTH_SECRET_KEY"] = "test-secret-key"

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.database import get_db_connection  # noqa: E402


class SocialMessagingFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.admin_token = cls._login("kuxiaowo", "12345678")
        cls.alice = cls._register("alice_user", "Alice")
        cls.bob = cls._register("bob_user", "Bob")
        cls.charlie = cls._register("charlie_user", "Charlie")
        cls.alice_token = cls._login("alice_user", "password123")
        cls.bob_token = cls._login("bob_user", "password123")
        cls.charlie_token = cls._login("charlie_user", "password123")

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
                "resourceUrl": "https://example.com/videos/teacher-class.mp4",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        teacher_resource = response.json()
        self.assertEqual(teacher_resource["category"], "teacher")
        self.assertEqual(teacher_resource["label"], "老师驾到")
        self.assertEqual(teacher_resource["image"], "")
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
                "title": "缺少简介的视频",
                "year": 2026,
                "category": "teacher",
                "resourceUrl": "https://example.com/videos/missing-description.mp4",
            },
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("description", response.json()["detail"])

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

    def test_03_person_claim_and_admin_review(self) -> None:
        project = self.client.get("/api/projects/1").json()["data"]
        person_id = project["memberList"][0]["personId"]
        response = self.client.post(
            f"/api/people/{person_id}/claims",
            headers=self._headers(self.alice_token),
            json={"note": "校园噪音地图负责人"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        claim_id = response.json()["claimId"]

        pending = self.client.get(
            "/api/admin/person-claims?status=pending",
            headers=self._headers(self.admin_token),
        )
        self.assertEqual(pending.status_code, 200, pending.text)
        self.assertIn(claim_id, [item["id"] for item in pending.json()["data"]])

        response = self.client.patch(
            f"/api/admin/person-claims/{claim_id}",
            headers=self._headers(self.admin_token),
            json={"status": "approved"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        project = self.client.get("/api/projects/1").json()["data"]
        leader = project["memberList"][0]
        self.assertTrue(leader["registered"])
        self.assertEqual(leader["userId"], self.alice["id"])

    def test_04_stranger_request_message_read_recall_and_block(self) -> None:
        response = self.client.post(
            "/api/conversations",
            headers=self._headers(self.alice_token),
            json={"targetUserId": self.bob["id"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        conversation_id = response.json()["data"]["id"]
        self.assertEqual(response.json()["data"]["requestStatus"], "pending")

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

        second = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(self.alice_token),
            json={"type": "text", "body": "第二条", "clientMessageId": "alice-second-before-accept"},
        )
        self.assertEqual(second.status_code, 403)

        requests = self.client.get(
            "/api/conversations?scope=requests",
            headers=self._headers(self.bob_token),
        )
        self.assertEqual(requests.status_code, 200, requests.text)
        self.assertEqual(requests.json()["data"][0]["id"], conversation_id)

        history = self.client.get(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(self.bob_token),
        )
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual(history.json()["data"][0]["body"], "你好，我想聊聊 CAS")

        accepted = self.client.post(
            f"/api/conversations/{conversation_id}/request",
            headers=self._headers(self.bob_token),
            json={"action": "accept"},
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)

        second = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(self.alice_token),
            json={"type": "text", "body": "现在可以继续了", "clientMessageId": "alice-second"},
        )
        self.assertEqual(second.status_code, 200, second.text)
        second_message_id = second.json()["data"]["id"]

        counts = self.client.get(
            "/api/messages/unread-count",
            headers=self._headers(self.bob_token),
        ).json()
        self.assertEqual(counts["unread"], 2)

        read = self.client.post(
            f"/api/conversations/{conversation_id}/read",
            headers=self._headers(self.bob_token),
            json={"messageId": second_message_id},
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

        recalled = self.client.post(
            f"/api/messages/{first_message_id}/recall",
            headers=self._headers(self.alice_token),
        )
        self.assertEqual(recalled.status_code, 200, recalled.text)

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

    def test_05_declined_request_cannot_receive_more_messages(self) -> None:
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
            json={"type": "text", "body": "陌生人请求", "clientMessageId": "decline-first"},
        )
        self.assertEqual(first.status_code, 200, first.text)
        declined = self.client.post(
            f"/api/conversations/{conversation_id}/request",
            headers=self._headers(self.charlie_token),
            json={"action": "decline"},
        )
        self.assertEqual(declined.status_code, 200, declined.text)
        denied = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            headers=self._headers(self.bob_token),
            json={"type": "text", "body": "拒绝后不应继续发送", "clientMessageId": "decline-second"},
        )
        self.assertEqual(denied.status_code, 403)

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
                "summary": "先作为草稿保存",
                "content": "第一段。\n\n第二段。",
                "status": "draft",
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

    def test_09_admin_project_two_stage_creation_and_member_contacts(self) -> None:
        created = self.client.post(
            "/api/admin/projects",
            headers=self._headers(self.admin_token),
            json={
                "name": "分阶段管理测试",
                "category": "测试分类",
                "year": 2026,
                "icon": "/CAS/test/icon.png",
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
        self.assertEqual(project["icon"], "/CAS/test/icon.png")

        created_without_icon = self.client.post(
            "/api/admin/projects",
            headers=self._headers(self.admin_token),
            json={
                "name": "无图标占位测试",
                "category": "测试分类",
                "year": 2026,
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
                        "images": ["/CAS/test/activity-1.jpg", "/CAS/test/activity-2.jpg"],
                    },
                    {"content": "没有照片的第二条动态", "images": []},
                ],
            },
        )
        self.assertEqual(updated_content.status_code, 200, updated_content.text)
        self.assertEqual(updated_content.json()["media"], [])
        self.assertEqual(
            updated_content.json()["updates"][0],
            {
                "content": "项目创建后补充的第一条动态",
                "images": ["/CAS/test/activity-1.jpg", "/CAS/test/activity-2.jpg"],
            },
        )

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
            ["/CAS/test/activity-1.jpg", "/CAS/test/activity-2.jpg"],
        )


if __name__ == "__main__":
    unittest.main()
