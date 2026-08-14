"""一对一私信的数据访问与权限校验。"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from backend.database import Cursor, get_db_connection


def format_public_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "displayName": row.get("display_name"),
    }


def search_users(viewer_user_id: int, query: str, limit: int = 20) -> list[dict[str, Any]]:
    keyword = query.strip()
    if not keyword:
        return []
    like_keyword = f"%{keyword}%"
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, username, display_name
                FROM users
                WHERE id <> %s
                  AND is_active = 1
                  AND (username LIKE %s OR display_name LIKE %s)
                ORDER BY
                  CASE WHEN username = %s THEN 0 ELSE 1 END,
                  username ASC
                LIMIT %s
                """,
                (viewer_user_id, like_keyword, like_keyword, keyword, limit),
            )
            rows = cursor.fetchall()
    return [format_public_user(row) for row in rows]


def _conversation_for_user(cursor: Cursor, conversation_id: int, user_id: int) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT *
        FROM direct_conversations
        WHERE id = %s AND (user_low_id = %s OR user_high_id = %s)
        LIMIT 1
        """,
        (conversation_id, user_id, user_id),
    )
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return row


def _format_message(row: dict[str, Any], viewer_user_id: int) -> dict[str, Any]:
    return {
        "id": row["id"],
        "conversationId": row["conversation_id"],
        "senderId": row["sender_id"],
        "content": row["content"],
        "createdAt": row.get("created_at"),
        "readAt": row.get("read_at"),
        "isMine": row["sender_id"] == viewer_user_id,
    }


def _conversation_summary(
    cursor: Cursor,
    conversation: dict[str, Any],
    viewer_user_id: int,
) -> dict[str, Any]:
    other_user_id = (
        conversation["user_high_id"]
        if conversation["user_low_id"] == viewer_user_id
        else conversation["user_low_id"]
    )
    cursor.execute(
        "SELECT id, username, display_name FROM users WHERE id = %s LIMIT 1",
        (other_user_id,),
    )
    other_user = cursor.fetchone()
    if other_user is None:
        raise HTTPException(status_code=404, detail="对方账号不存在")

    cursor.execute(
        """
        SELECT *
        FROM direct_messages
        WHERE conversation_id = %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (conversation["id"],),
    )
    last_message = cursor.fetchone()
    cursor.execute(
        """
        SELECT COUNT(*) AS unread_count
        FROM direct_messages
        WHERE conversation_id = %s
          AND sender_id <> %s
          AND read_at IS NULL
        """,
        (conversation["id"], viewer_user_id),
    )
    unread_count = cursor.fetchone()["unread_count"]
    return {
        "id": conversation["id"],
        "otherUser": format_public_user(other_user),
        "lastMessage": None if last_message is None else _format_message(last_message, viewer_user_id),
        "unreadCount": unread_count,
        "updatedAt": conversation.get("updated_at"),
    }


def list_conversations(user_id: int) -> list[dict[str, Any]]:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM direct_conversations
                WHERE user_low_id = %s OR user_high_id = %s
                ORDER BY updated_at DESC, id DESC
                """,
                (user_id, user_id),
            )
            conversations = cursor.fetchall()
            return [_conversation_summary(cursor, item, user_id) for item in conversations]


def get_or_create_conversation(user_id: int, other_user_id: int) -> dict[str, Any]:
    if user_id == other_user_id:
        raise HTTPException(status_code=422, detail="不能给自己发私信")
    low_id, high_id = sorted((user_id, other_user_id))
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM users WHERE id = %s AND is_active = 1 LIMIT 1",
                (other_user_id,),
            )
            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="用户不存在或账号不可用")
            cursor.execute(
                """
                INSERT OR IGNORE INTO direct_conversations (user_low_id, user_high_id)
                VALUES (%s, %s)
                """,
                (low_id, high_id),
            )
            cursor.execute(
                """
                SELECT * FROM direct_conversations
                WHERE user_low_id = %s AND user_high_id = %s
                LIMIT 1
                """,
                (low_id, high_id),
            )
            conversation = cursor.fetchone()
            return _conversation_summary(cursor, conversation, user_id)


def list_messages(
    conversation_id: int,
    user_id: int,
    before_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            _conversation_for_user(cursor, conversation_id, user_id)
            params: list[Any] = [conversation_id]
            before_sql = ""
            if before_id is not None:
                before_sql = "AND id < %s"
                params.append(before_id)
            params.append(limit)
            cursor.execute(
                f"""
                SELECT *
                FROM direct_messages
                WHERE conversation_id = %s {before_sql}
                ORDER BY id DESC
                LIMIT %s
                """,
                params,
            )
            rows = list(reversed(cursor.fetchall()))
    return [_format_message(row, user_id) for row in rows]


def send_message(conversation_id: int, sender_id: int, content: str) -> dict[str, Any]:
    normalized_content = content.strip()
    if not normalized_content:
        raise HTTPException(status_code=422, detail="消息内容不能为空")
    if len(normalized_content) > 2000:
        raise HTTPException(status_code=422, detail="消息不能超过 2000 字")

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            conversation = _conversation_for_user(cursor, conversation_id, sender_id)
            other_user_id = (
                conversation["user_high_id"]
                if conversation["user_low_id"] == sender_id
                else conversation["user_low_id"]
            )
            cursor.execute(
                "SELECT id FROM users WHERE id = %s AND is_active = 1 LIMIT 1",
                (other_user_id,),
            )
            if cursor.fetchone() is None:
                raise HTTPException(status_code=409, detail="对方账号当前不可用")
            cursor.execute(
                """
                INSERT INTO direct_messages (conversation_id, sender_id, content)
                VALUES (%s, %s, %s)
                """,
                (conversation_id, sender_id, normalized_content),
            )
            message_id = cursor.lastrowid
            cursor.execute("SELECT * FROM direct_messages WHERE id = %s", (message_id,))
            message = cursor.fetchone()
    return _format_message(message, sender_id)


def mark_conversation_read(
    conversation_id: int,
    user_id: int,
    up_to_message_id: int | None = None,
) -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            _conversation_for_user(cursor, conversation_id, user_id)
            params: list[Any] = [conversation_id, user_id]
            upper_bound_sql = ""
            if up_to_message_id is not None:
                upper_bound_sql = "AND id <= %s"
                params.append(up_to_message_id)
            cursor.execute(
                f"""
                UPDATE direct_messages
                SET read_at = CURRENT_TIMESTAMP
                WHERE conversation_id = %s
                  AND sender_id <> %s
                  AND read_at IS NULL
                  {upper_bound_sql}
                """,
                params,
            )


def get_unread_count(user_id: int) -> int:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS unread_count
                FROM direct_messages message
                JOIN direct_conversations conversation ON conversation.id = message.conversation_id
                WHERE (conversation.user_low_id = %s OR conversation.user_high_id = %s)
                  AND message.sender_id <> %s
                  AND message.read_at IS NULL
                """,
                (user_id, user_id, user_id),
            )
            return cursor.fetchone()["unread_count"]
