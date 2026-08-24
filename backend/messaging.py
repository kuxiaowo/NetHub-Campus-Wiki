"""一对一私信：统一会话、动态限流、未读、撤回和实时事件。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlite3 import IntegrityError
import secrets
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect

from backend.auth import get_current_user
from backend.database import get_db_connection
from backend.project_assets import project_icon_url

router = APIRouter(prefix="/api", tags=["messages"])

MAX_MESSAGE_LENGTH = 2000
RECALL_WINDOW_SECONDS = 120
SEND_RATE_PER_MINUTE = 30
STREAM_TICKET_TTL_SECONDS = 60
_stream_tickets: dict[str, tuple[int, float]] = {}


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: dict[int, set[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.setdefault(user_id, set()).add(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        sockets = self.connections.get(user_id)
        if not sockets:
            return
        sockets.discard(websocket)
        if not sockets:
            self.connections.pop(user_id, None)

    async def send(self, user_id: int, payload: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for websocket in list(self.connections.get(user_id, set())):
            try:
                await websocket.send_json(payload)
            except Exception:  # noqa: BLE001 - stale browser sockets are expected.
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(user_id, websocket)


manager = ConnectionManager()


def _require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def _direct_key(first_user_id: int, second_user_id: int) -> str:
    low, high = sorted((first_user_id, second_user_id))
    return f"{low}:{high}"


def _ensure_target_user(cursor: Any, user_id: int) -> dict[str, Any]:
    cursor.execute("SELECT * FROM users WHERE id = %s AND is_active = 1 LIMIT 1", (user_id,))
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return row


def _block_exists(cursor: Any, first_user_id: int, second_user_id: int) -> bool:
    cursor.execute(
        """
        SELECT 1 FROM user_blocks
        WHERE (blocker_id = %s AND blocked_id = %s)
           OR (blocker_id = %s AND blocked_id = %s)
        LIMIT 1
        """,
        (first_user_id, second_user_id, second_user_id, first_user_id),
    )
    return cursor.fetchone() is not None


def _follow_state(cursor: Any, sender_id: int, target_id: int) -> tuple[bool, bool]:
    cursor.execute(
        """
        SELECT
          EXISTS(
            SELECT 1 FROM user_follows
            WHERE follower_id = %s AND following_id = %s
          ) AS sender_follows,
          EXISTS(
            SELECT 1 FROM user_follows
            WHERE follower_id = %s AND following_id = %s
          ) AS target_follows
        """,
        (sender_id, target_id, target_id, sender_id),
    )
    row = cursor.fetchone()
    return bool(row["sender_follows"]), bool(row["target_follows"])


def _can_start_conversation(
    permission: str,
    sender_follows: bool,
    target_follows: bool,
) -> bool:
    if permission == "nobody":
        return False
    if permission == "following":
        return target_follows
    if permission == "mutual":
        return sender_follows and target_follows
    return True


def _message_dict(row: dict[str, Any]) -> dict[str, Any]:
    recalled = bool(row.get("recalled_at"))
    project = None
    if row.get("project_id") and row.get("project_name"):
        project = {
            "id": row["project_id"],
            "name": row["project_name"],
            "icon": project_icon_url(row.get("project_asset_dir"), row.get("project_icon")),
            "year": row.get("project_year"),
        }
    return {
        "id": row["id"],
        "conversationId": row["conversation_id"],
        "sender": {
            "id": row["sender_id"],
            "username": row.get("sender_username"),
            "displayName": row.get("sender_display_name"),
            "avatarUrl": row.get("sender_avatar_url"),
        },
        "type": row["message_type"],
        "body": "" if recalled else row.get("body", ""),
        "project": None if recalled else project,
        "replyToId": row.get("reply_to_id"),
        "recalled": recalled,
        "createdAt": row["created_at"],
    }


def _fetch_message(cursor: Any, message_id: int) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT
          m.*,
          u.username AS sender_username,
          u.display_name AS sender_display_name,
          u.avatar_url AS sender_avatar_url,
          p.name AS project_name,
          p.icon AS project_icon,
          p.asset_dir AS project_asset_dir,
          p.year AS project_year
        FROM messages m
        JOIN users u ON u.id = m.sender_id
        LEFT JOIN projects p ON p.id = m.project_id
        WHERE m.id = %s
        LIMIT 1
        """,
        (message_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    return row


def _conversation_user_ids(cursor: Any, conversation_id: int) -> list[int]:
    cursor.execute(
        "SELECT user_id FROM conversation_members WHERE conversation_id = %s",
        (conversation_id,),
    )
    return [row["user_id"] for row in cursor.fetchall()]


@router.post("/conversations")
def open_conversation(
    payload: dict[str, Any],
    user: dict[str, Any] = Depends(get_current_user),
):
    try:
        target_user_id = int(payload.get("targetUserId"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="targetUserId 无效") from None
    if target_user_id == user["id"]:
        raise HTTPException(status_code=422, detail="不能给自己发私信")

    direct_key = _direct_key(user["id"], target_user_id)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            target = _ensure_target_user(cursor, target_user_id)
            if _block_exists(cursor, user["id"], target_user_id):
                raise HTTPException(status_code=403, detail="黑名单关系下无法私信")
            cursor.execute(
                "SELECT id FROM conversations WHERE direct_key = %s LIMIT 1",
                (direct_key,),
            )
            existing = cursor.fetchone()
            if existing is not None:
                return {"data": {"id": existing["id"], "created": False}}

            sender_follows, target_follows = _follow_state(cursor, user["id"], target_user_id)
            if not _can_start_conversation(
                target.get("messaging_permission") or "everyone",
                sender_follows,
                target_follows,
            ):
                raise HTTPException(status_code=403, detail="对方的私信权限不允许发起会话")

            cursor.execute(
                "INSERT OR IGNORE INTO conversations (direct_key) VALUES (%s)",
                (direct_key,),
            )
            if cursor.rowcount == 0:
                cursor.execute(
                    "SELECT id FROM conversations WHERE direct_key = %s LIMIT 1",
                    (direct_key,),
                )
                concurrent = cursor.fetchone()
                return {"data": {"id": concurrent["id"], "created": False}}
            conversation_id = cursor.lastrowid
            cursor.executemany(
                """
                INSERT INTO conversation_members (conversation_id, user_id)
                VALUES (%s, %s)
                """,
                [
                    (conversation_id, user["id"]),
                    (conversation_id, target_user_id),
                ],
            )
    return {
        "data": {
            "id": conversation_id,
            "created": True,
        }
    }


@router.get("/conversations")
def list_conversations(
    user: dict[str, Any] = Depends(get_current_user),
):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  c.id,
                  c.last_message_at,
                  cm.last_read_message_id,
                  other.id AS other_user_id,
                  other.username AS other_username,
                  other.display_name AS other_display_name,
                  other.avatar_url AS other_avatar_url,
                  other.campus_verified AS other_campus_verified,
                  lm.id AS last_message_id,
                  lm.sender_id AS last_sender_id,
                  lm.message_type AS last_message_type,
                  lm.body AS last_message_body,
                  lm.recalled_at AS last_message_recalled_at,
                  lm.created_at AS last_message_created_at,
                  (
                    SELECT COUNT(*)
                    FROM messages unread
                    WHERE unread.conversation_id = c.id
                      AND unread.sender_id <> %s
                      AND unread.recalled_at IS NULL
                      AND unread.id > COALESCE(cm.last_read_message_id, 0)
                  ) AS unread_count,
                  EXISTS(
                    SELECT 1 FROM user_blocks b
                    WHERE (b.blocker_id = %s AND b.blocked_id = other.id)
                       OR (b.blocker_id = other.id AND b.blocked_id = %s)
                  ) AS blocked
                FROM conversation_members cm
                JOIN conversations c ON c.id = cm.conversation_id
                JOIN conversation_members other_cm
                  ON other_cm.conversation_id = c.id AND other_cm.user_id <> cm.user_id
                JOIN users other ON other.id = other_cm.user_id AND other.is_active = 1
                LEFT JOIN messages lm ON lm.id = c.last_message_id
                WHERE cm.user_id = %s
                  AND cm.hidden_at IS NULL
                  AND c.last_message_id IS NOT NULL
                ORDER BY c.last_message_at DESC, c.id DESC
                """,
                (user["id"], user["id"], user["id"], user["id"]),
            )
            rows = cursor.fetchall()
    return {
        "data": [
            {
                "id": row["id"],
                "otherUser": {
                    "id": row["other_user_id"],
                    "username": row["other_username"],
                    "displayName": row.get("other_display_name"),
                    "avatarUrl": row.get("other_avatar_url"),
                    "campusVerified": bool(row.get("other_campus_verified")),
                },
                "lastMessage": (
                    {
                        "id": row["last_message_id"],
                        "senderId": row.get("last_sender_id"),
                        "type": row.get("last_message_type"),
                        "body": (
                            "消息已撤回"
                            if row.get("last_message_recalled_at")
                            else row.get("last_message_body") or "项目卡片"
                        ),
                        "createdAt": row.get("last_message_created_at"),
                    }
                    if row.get("last_message_id")
                    else None
                ),
                "unreadCount": row.get("unread_count", 0),
                "blocked": bool(row.get("blocked")),
                "lastMessageAt": row["last_message_at"],
            }
            for row in rows
        ]
    }


@router.get("/conversations/{conversation_id}/messages")
def list_messages(
    conversation_id: int,
    before: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    user: dict[str, Any] = Depends(get_current_user),
):
    message_params: list[Any] = [conversation_id]
    before_sql = ""
    if before is not None:
        before_sql = "AND m.id < %s"
        message_params.append(before)
    message_params.append(limit)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT cm.last_read_message_id,
                       other_cm.last_read_message_id AS other_last_read_message_id,
                       other_cm.user_id AS other_user_id
                FROM conversation_members cm
                JOIN conversation_members other_cm
                  ON other_cm.conversation_id = cm.conversation_id
                 AND other_cm.user_id <> cm.user_id
                WHERE cm.conversation_id = %s AND cm.user_id = %s
                LIMIT 1
                """,
                (conversation_id, user["id"]),
            )
            membership = cursor.fetchone()
            if membership is None:
                raise HTTPException(status_code=404, detail="会话不存在")
            cursor.execute(
                f"""
                SELECT
                  m.*,
                  u.username AS sender_username,
                  u.display_name AS sender_display_name,
                  u.avatar_url AS sender_avatar_url,
                  p.name AS project_name,
                  p.icon AS project_icon,
                  p.asset_dir AS project_asset_dir,
                  p.year AS project_year
                FROM messages m
                JOIN users u ON u.id = m.sender_id
                LEFT JOIN projects p ON p.id = m.project_id
                WHERE m.conversation_id = %s
                  {before_sql}
                ORDER BY m.id DESC
                LIMIT %s
                """,
                message_params,
            )
            rows = list(reversed(cursor.fetchall()))
    return {
        "data": [_message_dict(row) for row in rows],
        "lastReadMessageId": membership.get("last_read_message_id"),
        "otherLastReadMessageId": membership.get("other_last_read_message_id"),
        "otherUserId": membership["other_user_id"],
    }


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: int,
    payload: dict[str, Any],
    user: dict[str, Any] = Depends(get_current_user),
):
    message_type = str(payload.get("type") or "text")
    if message_type not in {"text", "project"}:
        raise HTTPException(status_code=422, detail="消息类型无效")
    body = str(payload.get("body") or "").strip()
    if len(body) > MAX_MESSAGE_LENGTH:
        raise HTTPException(status_code=422, detail=f"消息不能超过 {MAX_MESSAGE_LENGTH} 字")
    project_id: int | None = None
    if message_type == "text" and not body:
        raise HTTPException(status_code=422, detail="消息内容不能为空")
    if message_type == "project":
        try:
            project_id = int(payload.get("projectId"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="项目卡片无效") from None

    client_message_id = str(payload.get("clientMessageId") or "").strip() or None
    if client_message_id and len(client_message_id) > 100:
        raise HTTPException(status_code=422, detail="clientMessageId 过长")
    reply_to_id = payload.get("replyToId")
    if reply_to_id is not None:
        try:
            reply_to_id = int(reply_to_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="回复消息 ID 无效") from None

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Serialize quota checks and insertion so concurrent requests cannot
            # both consume the same sender/recipient/day allowance.
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                """
                SELECT other_cm.user_id AS other_user_id
                FROM conversation_members cm
                JOIN conversation_members other_cm
                  ON other_cm.conversation_id = cm.conversation_id
                 AND other_cm.user_id <> cm.user_id
                WHERE cm.conversation_id = %s AND cm.user_id = %s
                LIMIT 1
                """,
                (conversation_id, user["id"]),
            )
            membership = cursor.fetchone()
            if membership is None:
                raise HTTPException(status_code=404, detail="会话不存在")
            other_user_id = membership["other_user_id"]
            if _block_exists(cursor, user["id"], other_user_id):
                raise HTTPException(status_code=403, detail="黑名单关系下无法私信")

            if client_message_id:
                cursor.execute(
                    """
                    SELECT id, conversation_id FROM messages
                    WHERE sender_id = %s AND client_message_id = %s
                    LIMIT 1
                    """,
                    (user["id"], client_message_id),
                )
                idempotent_message = cursor.fetchone()
                if idempotent_message is not None:
                    if idempotent_message["conversation_id"] != conversation_id:
                        raise HTTPException(status_code=409, detail="clientMessageId 已用于其他会话")
                    return {"data": _message_dict(_fetch_message(cursor, idempotent_message["id"]))}

            cursor.execute(
                """
                SELECT
                  EXISTS(
                    SELECT 1 FROM user_follows
                    WHERE follower_id = %s AND following_id = %s
                  ) AS recipient_follows_sender,
                  EXISTS(
                    SELECT 1 FROM messages
                    WHERE conversation_id = %s AND sender_id = %s
                  ) AS recipient_has_replied
                """,
                (other_user_id, user["id"], conversation_id, other_user_id),
            )
            contact = cursor.fetchone()
            if not contact["recipient_follows_sender"] and not contact["recipient_has_replied"]:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS sent_today
                    FROM messages
                    WHERE conversation_id = %s AND sender_id = %s
                      AND date(created_at, '+8 hours') = date('now', '+8 hours')
                    """,
                    (conversation_id, user["id"]),
                )
                if cursor.fetchone()["sent_today"] >= 1:
                    raise HTTPException(
                        status_code=429,
                        detail="对方回复或关注你前，每天最多发送一条消息",
                    )

            cursor.execute(
                """
                SELECT COUNT(*) AS recent_count
                FROM messages
                WHERE sender_id = %s
                  AND created_at >= datetime('now', '-1 minute')
                """,
                (user["id"],),
            )
            if cursor.fetchone()["recent_count"] >= SEND_RATE_PER_MINUTE:
                raise HTTPException(status_code=429, detail="发送过于频繁，请稍后再试")

            if project_id is not None:
                cursor.execute("SELECT id FROM projects WHERE id = %s LIMIT 1", (project_id,))
                if cursor.fetchone() is None:
                    raise HTTPException(status_code=404, detail="项目不存在")
            if reply_to_id is not None:
                cursor.execute(
                    """
                    SELECT id FROM messages
                    WHERE id = %s AND conversation_id = %s
                    LIMIT 1
                    """,
                    (reply_to_id, conversation_id),
                )
                if cursor.fetchone() is None:
                    raise HTTPException(status_code=422, detail="回复的消息不在当前会话中")

            try:
                cursor.execute(
                    """
                    INSERT INTO messages
                      (conversation_id, sender_id, message_type, body, project_id,
                       client_message_id, reply_to_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        conversation_id,
                        user["id"],
                        message_type,
                        body,
                        project_id,
                        client_message_id,
                        reply_to_id,
                    ),
                )
                message_id = cursor.lastrowid
            except IntegrityError:
                if not client_message_id:
                    raise
                cursor.execute(
                    """
                    SELECT id, conversation_id FROM messages
                    WHERE sender_id = %s AND client_message_id = %s
                    LIMIT 1
                    """,
                    (user["id"], client_message_id),
                )
                existing = cursor.fetchone()
                if existing is None:
                    raise
                if existing["conversation_id"] != conversation_id:
                    raise HTTPException(status_code=409, detail="clientMessageId 已用于其他会话")
                message_id = existing["id"]

            cursor.execute(
                """
                UPDATE conversations
                SET last_message_id = %s, last_message_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (message_id, conversation_id),
            )
            cursor.execute(
                "UPDATE conversation_members SET hidden_at = NULL WHERE conversation_id = %s",
                (conversation_id,),
            )
            message = _message_dict(_fetch_message(cursor, message_id))

    event = {"event": "message", "conversationId": conversation_id, "message": message}
    await manager.send(user["id"], event)
    await manager.send(other_user_id, event)
    return {"data": message}


@router.post("/conversations/{conversation_id}/read")
async def mark_conversation_read(
    conversation_id: int,
    payload: dict[str, Any],
    user: dict[str, Any] = Depends(get_current_user),
):
    requested_message_id = payload.get("messageId")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT MAX(m.id) AS max_id
                FROM messages m
                JOIN conversation_members cm ON cm.conversation_id = m.conversation_id
                WHERE m.conversation_id = %s AND cm.user_id = %s
                """,
                (conversation_id, user["id"]),
            )
            row = cursor.fetchone()
            if row is None or row.get("max_id") is None:
                raise HTTPException(status_code=404, detail="会话不存在或暂无消息")
            max_id = row["max_id"]
            if requested_message_id is not None:
                try:
                    max_id = min(max_id, int(requested_message_id))
                except (TypeError, ValueError):
                    raise HTTPException(status_code=422, detail="messageId 无效") from None
            cursor.execute(
                """
                UPDATE conversation_members
                SET last_read_message_id = CASE
                  WHEN COALESCE(last_read_message_id, 0) < %s THEN %s
                  ELSE last_read_message_id
                END
                WHERE conversation_id = %s AND user_id = %s
                """,
                (max_id, max_id, conversation_id, user["id"]),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="会话不存在")
            user_ids = _conversation_user_ids(cursor, conversation_id)
    event = {
        "event": "read",
        "conversationId": conversation_id,
        "userId": user["id"],
        "messageId": max_id,
    }
    for user_id in user_ids:
        await manager.send(user_id, event)
    return {"ok": True, "lastReadMessageId": max_id}


@router.delete("/conversations/{conversation_id}")
def hide_conversation(
    conversation_id: int,
    user: dict[str, Any] = Depends(get_current_user),
):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE conversation_members
                SET hidden_at = CURRENT_TIMESTAMP
                WHERE conversation_id = %s AND user_id = %s
                """,
                (conversation_id, user["id"]),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


@router.post("/messages/{message_id}/recall")
async def recall_message(message_id: int, user: dict[str, Any] = Depends(get_current_user)):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            row = _fetch_message(cursor, message_id)
            if row["sender_id"] != user["id"]:
                raise HTTPException(status_code=403, detail="只能撤回自己发送的消息")
            if row.get("recalled_at"):
                return {"ok": True}
            created_at = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - created_at > timedelta(seconds=RECALL_WINDOW_SECONDS):
                raise HTTPException(status_code=409, detail="消息已超过可撤回时间")
            cursor.execute(
                "UPDATE messages SET recalled_at = CURRENT_TIMESTAMP WHERE id = %s",
                (message_id,),
            )
            conversation_id = row["conversation_id"]
            user_ids = _conversation_user_ids(cursor, conversation_id)
    event = {
        "event": "recall",
        "conversationId": conversation_id,
        "messageId": message_id,
    }
    for user_id in user_ids:
        await manager.send(user_id, event)
    return {"ok": True}


@router.post("/messages/{message_id}/reports")
def report_message(
    message_id: int,
    payload: dict[str, Any],
    user: dict[str, Any] = Depends(get_current_user),
):
    reason = str(payload.get("reason") or "").strip()
    if not reason or len(reason) > 300:
        raise HTTPException(status_code=422, detail="举报理由长度应为 1-300 字")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            row = _fetch_message(cursor, message_id)
            if row["sender_id"] == user["id"]:
                raise HTTPException(status_code=422, detail="不能举报自己发送的消息")
            cursor.execute(
                """
                SELECT 1 FROM conversation_members
                WHERE conversation_id = %s AND user_id = %s
                """,
                (row["conversation_id"], user["id"]),
            )
            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="消息不存在")
            cursor.execute(
                """
                INSERT INTO message_reports (message_id, reporter_id, reason)
                VALUES (%s, %s, %s)
                ON CONFLICT(message_id, reporter_id) DO UPDATE SET
                  reason = excluded.reason,
                  status = 'pending'
                """,
                (message_id, user["id"], reason),
            )
    return {"ok": True}


@router.get("/admin/message-reports")
def admin_list_message_reports(
    status: str = Query(default="pending", pattern="^(pending|resolved|dismissed)$"),
    _: dict[str, Any] = Depends(_require_admin),
):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  mr.*,
                  m.body,
                  m.recalled_at,
                  sender.id AS sender_id,
                  sender.username AS sender_username,
                  reporter.username AS reporter_username
                FROM message_reports mr
                JOIN messages m ON m.id = mr.message_id
                JOIN users sender ON sender.id = m.sender_id
                JOIN users reporter ON reporter.id = mr.reporter_id
                WHERE mr.status = %s
                ORDER BY mr.created_at ASC, mr.id ASC
                """,
                (status,),
            )
            rows = cursor.fetchall()
    return {
        "data": [
            {
                "id": row["id"],
                "messageId": row["message_id"],
                "messageBody": row["body"],
                "messageRecalled": bool(row.get("recalled_at")),
                "senderId": row["sender_id"],
                "senderUsername": row["sender_username"],
                "reporterId": row["reporter_id"],
                "reporterUsername": row["reporter_username"],
                "reason": row["reason"],
                "status": row["status"],
                "createdAt": row["created_at"],
            }
            for row in rows
        ]
    }


@router.patch("/admin/message-reports/{report_id}")
def admin_review_message_report(
    report_id: int,
    payload: dict[str, Any],
    admin: dict[str, Any] = Depends(_require_admin),
):
    status = str(payload.get("status") or "")
    if status not in {"resolved", "dismissed"}:
        raise HTTPException(status_code=422, detail="处理状态只能是 resolved 或 dismissed")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE message_reports
                SET status = %s, resolved_at = CURRENT_TIMESTAMP, resolved_by = %s
                WHERE id = %s AND status = 'pending'
                """,
                (status, admin["id"], report_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="待处理举报不存在")
    return {"ok": True, "status": status}


@router.get("/messages/unread-count")
def unread_count(user: dict[str, Any] = Depends(get_current_user)):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  SUM((
                    SELECT COUNT(*) FROM messages m
                    WHERE m.conversation_id = cm.conversation_id
                      AND m.sender_id <> cm.user_id
                      AND m.recalled_at IS NULL
                      AND m.id > COALESCE(cm.last_read_message_id, 0)
                  )) AS unread
                FROM conversation_members cm
                WHERE cm.user_id = %s AND cm.hidden_at IS NULL
                """,
                (user["id"],),
            )
            row = cursor.fetchone()
    return {"unread": int(row.get("unread") or 0)}


@router.post("/messages/stream-ticket")
def create_stream_ticket(user: dict[str, Any] = Depends(get_current_user)):
    now = time.time()
    for ticket, (_, expires_at) in list(_stream_tickets.items()):
        if expires_at <= now:
            _stream_tickets.pop(ticket, None)
    ticket = secrets.token_urlsafe(32)
    _stream_tickets[ticket] = (user["id"], now + STREAM_TICKET_TTL_SECONDS)
    return {"ticket": ticket, "expiresIn": STREAM_TICKET_TTL_SECONDS}


@router.websocket("/messages/ws")
async def message_stream(websocket: WebSocket):
    ticket = websocket.query_params.get("ticket", "")
    ticket_data = _stream_tickets.pop(ticket, None)
    if ticket_data is None or ticket_data[1] <= time.time():
        await websocket.close(code=4401)
        return
    user_id = ticket_data[0]
    await manager.connect(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
