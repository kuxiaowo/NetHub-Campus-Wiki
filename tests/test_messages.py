import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

import backend.database as database
from backend.messages import (
    get_user_profile,
    get_or_create_conversation,
    get_unread_count,
    list_messages,
    mark_conversation_read,
    send_message,
)


class DirectMessageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "messages.db"
        self.original_get_database_path = database.get_database_path
        database.get_database_path = lambda: self.database_path
        database._INITIALIZED_DATABASES.clear()

        with database.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO users (username, password_hash, display_name) VALUES (%s, %s, %s)",
                    ("student_a", "test", "学生甲"),
                )
                self.first_user_id = cursor.lastrowid
                cursor.execute(
                    "INSERT INTO users (username, password_hash, display_name) VALUES (%s, %s, %s)",
                    ("student_b", "test", "学生乙"),
                )
                self.second_user_id = cursor.lastrowid
                cursor.execute(
                    "INSERT INTO users (username, password_hash, display_name) VALUES (%s, %s, %s)",
                    ("student_c", "test", "学生丙"),
                )
                self.third_user_id = cursor.lastrowid
                cursor.execute(
                    """
                    UPDATE project_members
                    SET user_id = %s
                    WHERE project_id = 1 AND role = 'leader'
                    """,
                    (self.first_user_id,),
                )

    def tearDown(self) -> None:
        database._INITIALIZED_DATABASES.clear()
        database.get_database_path = self.original_get_database_path
        self.temp_dir.cleanup()

    def test_send_unread_and_mark_read(self) -> None:
        conversation = get_or_create_conversation(self.first_user_id, self.second_user_id)
        duplicate = get_or_create_conversation(self.second_user_id, self.first_user_id)
        self.assertEqual(conversation["id"], duplicate["id"])

        sent = send_message(conversation["id"], self.first_user_id, "你好")
        self.assertTrue(sent["isMine"])
        self.assertEqual(get_unread_count(self.second_user_id), 1)

        received = list_messages(conversation["id"], self.second_user_id)
        self.assertEqual(received[0]["content"], "你好")
        self.assertFalse(received[0]["isMine"])

        mark_conversation_read(conversation["id"], self.second_user_id)
        self.assertEqual(get_unread_count(self.second_user_id), 0)

    def test_non_participant_cannot_read_or_send(self) -> None:
        conversation = get_or_create_conversation(self.first_user_id, self.second_user_id)
        with self.assertRaises(HTTPException) as read_error:
            list_messages(conversation["id"], self.third_user_id)
        self.assertEqual(read_error.exception.status_code, 404)

        with self.assertRaises(HTTPException) as send_error:
            send_message(conversation["id"], self.third_user_id, "越权消息")
        self.assertEqual(send_error.exception.status_code, 404)

    def test_cannot_message_self_or_send_blank_content(self) -> None:
        with self.assertRaises(HTTPException) as self_error:
            get_or_create_conversation(self.first_user_id, self.first_user_id)
        self.assertEqual(self_error.exception.status_code, 422)

        conversation = get_or_create_conversation(self.first_user_id, self.second_user_id)
        with self.assertRaises(HTTPException) as content_error:
            send_message(conversation["id"], self.first_user_id, "   ")
        self.assertEqual(content_error.exception.status_code, 422)

    def test_linked_user_profile_contains_cas_project(self) -> None:
        profile = get_user_profile(self.first_user_id)
        self.assertEqual(profile["username"], "student_a")
        self.assertEqual(profile["projects"][0]["id"], 1)
        self.assertEqual(profile["projects"][0]["memberRole"], "leader")

        with self.assertRaises(HTTPException) as missing_error:
            get_user_profile(999999)
        self.assertEqual(missing_error.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
