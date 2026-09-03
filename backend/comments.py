"""公告、项目和资源共用的两级评论区。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.auth import get_current_user, get_optional_current_user, public_user_identity
from backend.config import settings
from backend.database import get_db_connection

router = APIRouter(prefix="/api", tags=["comments"])

TARGET_TABLES = {
    "announcement": "announcements",
    "project": "projects",
    "resource": "resources",
}
MAX_COMMENT_LENGTH = settings.comment_max_length
COMMENT_RATE_PER_MINUTE = settings.comment_rate_per_minute


def _create_notification(
    cursor: Any,
    *,
    kind: str,
    recipient_id: int,
    actor_id: int,
    comment_id: int,
    target_type: str,
    target_id: int,
) -> None:
    if recipient_id == actor_id:
        return
    cursor.execute(
        """
        INSERT INTO comment_notifications
          (kind, recipient_id, actor_id, comment_id, target_type, target_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT(kind, recipient_id, actor_id, comment_id) DO UPDATE SET
          created_at = CURRENT_TIMESTAMP,
          read_at = NULL,
          target_type = excluded.target_type,
          target_id = excluded.target_id
        """,
        (kind, recipient_id, actor_id, comment_id, target_type, target_id),
    )


def _target_url(target_type: str, target_id: int, comment_id: int | None = None) -> str:
    routes = {
        "announcement": "/announcement.html",
        "project": "/detail.html",
        "resource": "/resource.html",
    }
    url = f"{routes.get(target_type, '/')}?id={target_id}"
    if comment_id:
        url += f"&commentId={comment_id}#comment-{comment_id}"
    return url


def _require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def _validate_target(cursor: Any, target_type: str, target_id: int) -> None:
    table = TARGET_TABLES.get(target_type)
    if table is None:
        raise HTTPException(status_code=422, detail="留言目标类型无效")
    extra = (
        " AND status = 'published' AND published_at <= CURRENT_TIMESTAMP"
        if target_type == "announcement"
        else ""
    )
    cursor.execute(f"SELECT id FROM {table} WHERE id = %s{extra} LIMIT 1", (target_id,))
    if cursor.fetchone() is None:
        raise HTTPException(status_code=404, detail="留言目标不存在")


def _comment_dict(row: dict[str, Any]) -> dict[str, Any]:
    deleted = row["status"] == "deleted"
    return {
        "id": row["id"],
        "targetType": row["target_type"],
        "targetId": row["target_id"],
        "content": "" if deleted else row["content"],
        "status": row["status"],
        "author": public_user_identity(
            row,
            id_key="user_id",
            username_key="username",
            display_name_key="display_name",
            avatar_url_key="avatar_url",
            deleted_at_key="deleted_at",
            campus_verified_key="campus_verified",
        ),
        "replyToUser": (
            public_user_identity(
                row,
                id_key="reply_to_user_id",
                username_key="reply_to_username",
                display_name_key="reply_to_display_name",
                avatar_url_key="reply_to_avatar_url",
                deleted_at_key="reply_to_deleted_at",
            )
            if row.get("reply_to_user_id")
            else None
        ),
        "parentId": row.get("parent_id"),
        "rootId": row.get("root_id"),
        "likeCount": int(row.get("like_count") or 0),
        "liked": bool(row.get("liked")),
        "replyCount": int(row.get("reply_count") or 0),
        "createdAt": row["created_at"],
        "updatedAt": row.get("updated_at"),
    }


def _select_fields(viewer_id: int | None) -> tuple[str, list[Any]]:
    viewer = int(viewer_id or 0)
    return (
        """
        c.*,
        u.username,
        u.display_name,
        u.avatar_url,
        u.campus_verified,
        u.deleted_at,
        reply_user.username AS reply_to_username,
        reply_user.display_name AS reply_to_display_name,
        reply_user.avatar_url AS reply_to_avatar_url,
        reply_user.deleted_at AS reply_to_deleted_at,
        (SELECT COUNT(*) FROM comment_likes cl WHERE cl.comment_id = c.id) AS like_count,
        EXISTS(
          SELECT 1 FROM comment_likes cl
          WHERE cl.comment_id = c.id AND cl.user_id = %s
        ) AS liked
        """,
        [viewer],
    )


@router.get("/comments")
def list_comments(
    target_type: str = Query(alias="targetType"),
    target_id: int = Query(alias="targetId", ge=1),
    sort: str = Query(default="hot", pattern="^(hot|latest)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=50),
    viewer: dict[str, Any] | None = Depends(get_optional_current_user),
):
    viewer_id = viewer["id"] if viewer else None
    select_fields, select_params = _select_fields(viewer_id)
    order_by = "like_count DESC, c.created_at DESC, c.id DESC" if sort == "hot" else "c.created_at DESC, c.id DESC"
    offset = (page - 1) * page_size
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            _validate_target(cursor, target_type, target_id)
            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM comments
                WHERE target_type = %s AND target_id = %s
                  AND status = 'visible'
                """,
                (target_type, target_id),
            )
            total = cursor.fetchone()["total"]
            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM comments
                WHERE target_type = %s AND target_id = %s
                  AND parent_id IS NULL AND status <> 'hidden'
                """,
                (target_type, target_id),
            )
            root_total = cursor.fetchone()["total"]
            cursor.execute(
                f"""
                SELECT {select_fields},
                  (
                    SELECT COUNT(*) FROM comments child
                    WHERE child.root_id = c.id
                      AND child.parent_id IS NOT NULL
                      AND child.status <> 'hidden'
                  ) AS reply_count
                FROM comments c
                JOIN users u ON u.id = c.user_id
                LEFT JOIN users reply_user ON reply_user.id = c.reply_to_user_id
                WHERE c.target_type = %s AND c.target_id = %s
                  AND c.parent_id IS NULL AND c.status <> 'hidden'
                ORDER BY {order_by}
                LIMIT %s OFFSET %s
                """,
                [*select_params, target_type, target_id, page_size, offset],
            )
            roots = cursor.fetchall()
            root_ids = [row["id"] for row in roots]
            replies_by_root: dict[int, list[dict[str, Any]]] = {root_id: [] for root_id in root_ids}
            if root_ids:
                placeholders = ", ".join(["%s"] * len(root_ids))
                reply_fields, reply_params = _select_fields(viewer_id)
                cursor.execute(
                    f"""
                    SELECT {reply_fields}, 0 AS reply_count
                    FROM comments c
                    JOIN users u ON u.id = c.user_id
                    LEFT JOIN users reply_user ON reply_user.id = c.reply_to_user_id
                    WHERE c.root_id IN ({placeholders})
                      AND c.parent_id IS NOT NULL
                      AND c.status <> 'hidden'
                    ORDER BY c.created_at ASC, c.id ASC
                    """,
                    [*reply_params, *root_ids],
                )
                for reply in cursor.fetchall():
                    replies_by_root[reply["root_id"]].append(_comment_dict(reply))

    data = []
    for root in roots:
        item = _comment_dict(root)
        item["replies"] = replies_by_root.get(root["id"], [])
        data.append(item)
    return {
        "data": data,
        "page": page,
        "pageSize": page_size,
        "total": total,
        "hasMore": offset + len(roots) < root_total,
    }


@router.get("/comments/{comment_id}/context")
def get_comment_context(
    comment_id: int,
    viewer: dict[str, Any] | None = Depends(get_optional_current_user),
):
    viewer_id = viewer["id"] if viewer else None
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, target_type, target_id, root_id, status
                FROM comments
                WHERE id = %s
                LIMIT 1
                """,
                (comment_id,),
            )
            focus = cursor.fetchone()
            if focus is None or focus["status"] != "visible":
                raise HTTPException(status_code=404, detail="该留言或回复已删除或不存在")

            _validate_target(cursor, focus["target_type"], focus["target_id"])
            root_id = focus.get("root_id") or focus["id"]
            select_fields, select_params = _select_fields(viewer_id)
            cursor.execute(
                f"""
                SELECT {select_fields},
                  (
                    SELECT COUNT(*) FROM comments child
                    WHERE child.root_id = c.id
                      AND child.parent_id IS NOT NULL
                      AND child.status <> 'hidden'
                  ) AS reply_count
                FROM comments c
                JOIN users u ON u.id = c.user_id
                LEFT JOIN users reply_user ON reply_user.id = c.reply_to_user_id
                WHERE c.id = %s AND c.target_type = %s AND c.target_id = %s
                  AND c.parent_id IS NULL AND c.status <> 'hidden'
                LIMIT 1
                """,
                [*select_params, root_id, focus["target_type"], focus["target_id"]],
            )
            root = cursor.fetchone()
            if root is None:
                raise HTTPException(status_code=404, detail="留言上下文不存在")

            reply_fields, reply_params = _select_fields(viewer_id)
            cursor.execute(
                f"""
                SELECT {reply_fields}, 0 AS reply_count
                FROM comments c
                JOIN users u ON u.id = c.user_id
                LEFT JOIN users reply_user ON reply_user.id = c.reply_to_user_id
                WHERE c.root_id = %s
                  AND c.parent_id IS NOT NULL
                  AND c.status <> 'hidden'
                ORDER BY c.created_at ASC, c.id ASC
                """,
                [*reply_params, root_id],
            )
            replies = [_comment_dict(row) for row in cursor.fetchall()]

    data = _comment_dict(root)
    data["replies"] = replies
    return {"data": data, "focusCommentId": comment_id}


@router.get("/comment-notifications")
def list_comment_notifications(
    kind: str = Query(pattern="^(reply|like)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=50),
    user: dict[str, Any] = Depends(get_current_user),
):
    offset = (page - 1) * page_size
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS total, COALESCE(MAX(id), 0) AS latest_id
                FROM comment_notifications
                WHERE recipient_id = %s AND kind = %s
                """,
                (user["id"], kind),
            )
            summary = cursor.fetchone()
            cursor.execute(
                """
                SELECT n.*,
                       actor.username AS actor_username,
                       actor.display_name AS actor_display_name,
                       actor.avatar_url AS actor_avatar_url,
                       actor.campus_verified AS actor_campus_verified,
                       actor.deleted_at AS actor_deleted_at,
                       c.content AS comment_content,
                       c.status AS comment_status,
                       CASE n.target_type
                         WHEN 'announcement' THEN a.title
                         WHEN 'project' THEN p.name
                         WHEN 'resource' THEN r.title
                       END AS target_title,
                       CASE n.target_type
                         WHEN 'announcement' THEN
                           a.id IS NOT NULL AND a.status = 'published'
                             AND a.published_at <= CURRENT_TIMESTAMP
                         WHEN 'project' THEN p.id IS NOT NULL
                         WHEN 'resource' THEN r.id IS NOT NULL
                         ELSE 0
                       END AS target_available
                FROM comment_notifications n
                JOIN users actor ON actor.id = n.actor_id
                LEFT JOIN comments c ON c.id = n.comment_id
                LEFT JOIN announcements a
                  ON n.target_type = 'announcement' AND a.id = n.target_id
                LEFT JOIN projects p
                  ON n.target_type = 'project' AND p.id = n.target_id
                LEFT JOIN resources r
                  ON n.target_type = 'resource' AND r.id = n.target_id
                WHERE n.recipient_id = %s AND n.kind = %s
                ORDER BY n.created_at DESC, n.id DESC
                LIMIT %s OFFSET %s
                """,
                (user["id"], kind, page_size, offset),
            )
            rows = cursor.fetchall()

    data = []
    for row in rows:
        comment_available = row.get("comment_status") == "visible"
        link_available = comment_available and bool(row.get("target_available"))
        data.append(
            {
                "id": row["id"],
                "kind": row["kind"],
                "actor": public_user_identity(
                    row,
                    id_key="actor_id",
                    username_key="actor_username",
                    display_name_key="actor_display_name",
                    avatar_url_key="actor_avatar_url",
                    deleted_at_key="actor_deleted_at",
                    campus_verified_key="actor_campus_verified",
                ),
                "comment": {
                    "id": row["comment_id"],
                    "content": row.get("comment_content") if comment_available else "",
                    "status": row.get("comment_status") or "missing",
                    "available": comment_available,
                },
                "target": {
                    "type": row["target_type"],
                    "id": row["target_id"],
                    "title": row.get("target_title") or "原内容已不存在",
                    "available": bool(row.get("target_available")),
                    "url": (
                        _target_url(row["target_type"], row["target_id"], row["comment_id"])
                        if link_available
                        else None
                    ),
                },
                "createdAt": row["created_at"],
                "read": row.get("read_at") is not None,
            }
        )
    total = int(summary.get("total") or 0)
    return {
        "data": data,
        "page": page,
        "pageSize": page_size,
        "total": total,
        "hasMore": offset + len(data) < total,
        "latestId": int(summary.get("latest_id") or 0),
    }


@router.post("/comment-notifications/read")
def read_comment_notifications(
    payload: dict[str, Any],
    user: dict[str, Any] = Depends(get_current_user),
):
    kind = str(payload.get("kind") or "")
    if kind not in {"reply", "like"}:
        raise HTTPException(status_code=422, detail="通知类型无效")
    try:
        through_id = int(payload.get("throughId"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="throughId 无效") from None
    if through_id < 0:
        raise HTTPException(status_code=422, detail="throughId 无效")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE comment_notifications
                SET read_at = CURRENT_TIMESTAMP
                WHERE recipient_id = %s AND kind = %s
                  AND id <= %s AND read_at IS NULL
                """,
                (user["id"], kind, through_id),
            )
    return {"ok": True}


@router.get("/message-center/unread-count")
def message_center_unread_count(user: dict[str, Any] = Depends(get_current_user)):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  (
                    SELECT COALESCE(SUM((
                      SELECT COUNT(*)
                      FROM messages m
                      WHERE m.conversation_id = cm.conversation_id
                        AND m.sender_id <> cm.user_id
                        AND m.recalled_at IS NULL
                        AND m.id > COALESCE(cm.last_read_message_id, 0)
                    )), 0)
                    FROM conversation_members cm
                    WHERE cm.user_id = %s AND cm.hidden_at IS NULL
                  ) AS messages,
                  (
                    SELECT COUNT(*) FROM comment_notifications n
                    WHERE n.recipient_id = %s AND n.kind = 'reply' AND n.read_at IS NULL
                  ) AS replies,
                  (
                    SELECT COUNT(*) FROM comment_notifications n
                    WHERE n.recipient_id = %s AND n.kind = 'like' AND n.read_at IS NULL
                  ) AS likes
                """,
                (user["id"], user["id"], user["id"]),
            )
            row = cursor.fetchone()
    messages = int(row.get("messages") or 0)
    replies = int(row.get("replies") or 0)
    likes = int(row.get("likes") or 0)
    return {
        "total": messages + replies + likes,
        "messages": messages,
        "replies": replies,
        "likes": likes,
    }


@router.post("/comments")
def create_comment(
    payload: dict[str, Any],
    user: dict[str, Any] = Depends(get_current_user),
):
    target_type = str(payload.get("targetType") or "")
    try:
        target_id = int(payload.get("targetId"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="targetId 无效") from None
    content = str(payload.get("content") or "").strip()
    if not content or len(content) > MAX_COMMENT_LENGTH:
        raise HTTPException(status_code=422, detail=f"留言长度应为 1-{MAX_COMMENT_LENGTH} 字")
    parent_id = payload.get("parentId")
    if parent_id is not None:
        try:
            parent_id = int(parent_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="parentId 无效") from None

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            _validate_target(cursor, target_type, target_id)
            cursor.execute(
                """
                SELECT COUNT(*) AS recent_count FROM comments
                WHERE user_id = %s AND created_at >= datetime('now', '-1 minute')
                """,
                (user["id"],),
            )
            if cursor.fetchone()["recent_count"] >= COMMENT_RATE_PER_MINUTE:
                raise HTTPException(status_code=429, detail="留言过于频繁，请稍后再试")

            root_id = None
            reply_to_user_id = None
            if parent_id is not None:
                cursor.execute(
                    """
                    SELECT * FROM comments
                    WHERE id = %s AND target_type = %s AND target_id = %s
                      AND status = 'visible'
                    LIMIT 1
                    """,
                    (parent_id, target_type, target_id),
                )
                parent = cursor.fetchone()
                if parent is None:
                    raise HTTPException(status_code=404, detail="回复的留言不存在")
                root_id = parent.get("root_id") or parent["id"]
                reply_to_user_id = parent["user_id"]
                cursor.execute(
                    """
                    SELECT 1 FROM user_blocks
                    WHERE (blocker_id = %s AND blocked_id = %s)
                       OR (blocker_id = %s AND blocked_id = %s)
                    LIMIT 1
                    """,
                    (user["id"], reply_to_user_id, reply_to_user_id, user["id"]),
                )
                if cursor.fetchone() is not None:
                    raise HTTPException(status_code=403, detail="黑名单关系下无法回复")

            cursor.execute(
                """
                INSERT INTO comments
                  (target_type, target_id, user_id, parent_id, root_id,
                   reply_to_user_id, content)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    target_type,
                    target_id,
                    user["id"],
                    parent_id,
                    root_id,
                    reply_to_user_id,
                    content,
                ),
            )
            comment_id = cursor.lastrowid
            if parent_id is None:
                cursor.execute("UPDATE comments SET root_id = %s WHERE id = %s", (comment_id, comment_id))
            elif reply_to_user_id is not None:
                _create_notification(
                    cursor,
                    kind="reply",
                    recipient_id=reply_to_user_id,
                    actor_id=user["id"],
                    comment_id=comment_id,
                    target_type=target_type,
                    target_id=target_id,
                )
    return {"data": {"id": comment_id}}


@router.delete("/comments/{comment_id}")
def delete_comment(comment_id: int, user: dict[str, Any] = Depends(get_current_user)):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT user_id, status FROM comments WHERE id = %s LIMIT 1", (comment_id,))
            comment = cursor.fetchone()
            if comment is None:
                raise HTTPException(status_code=404, detail="留言不存在")
            if comment["user_id"] != user["id"] and user["role"] != "admin":
                raise HTTPException(status_code=403, detail="只能删除自己的留言")
            if comment["status"] != "deleted":
                cursor.execute(
                    "UPDATE comments SET status = 'deleted', content = '' WHERE id = %s",
                    (comment_id,),
                )
    return {"ok": True}


@router.post("/comments/{comment_id}/like")
def like_comment(comment_id: int, user: dict[str, Any] = Depends(get_current_user)):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, user_id, target_type, target_id
                FROM comments
                WHERE id = %s
                LIMIT 1
                """,
                (comment_id,),
            )
            comment = cursor.fetchone()
            if comment is None or comment["status"] != "visible":
                raise HTTPException(status_code=404, detail="留言不存在")
            cursor.execute(
                """
                INSERT INTO comment_likes (comment_id, user_id)
                VALUES (%s, %s)
                ON CONFLICT(comment_id, user_id) DO NOTHING
                """,
                (comment_id, user["id"]),
            )
            if cursor.rowcount:
                _create_notification(
                    cursor,
                    kind="like",
                    recipient_id=comment["user_id"],
                    actor_id=user["id"],
                    comment_id=comment_id,
                    target_type=comment["target_type"],
                    target_id=comment["target_id"],
                )
    return {"ok": True}


@router.delete("/comments/{comment_id}/like")
def unlike_comment(comment_id: int, user: dict[str, Any] = Depends(get_current_user)):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM comment_likes WHERE comment_id = %s AND user_id = %s",
                (comment_id, user["id"]),
            )
    return {"ok": True}


@router.post("/comments/{comment_id}/reports")
def report_comment(
    comment_id: int,
    payload: dict[str, Any],
    user: dict[str, Any] = Depends(get_current_user),
):
    reason = str(payload.get("reason") or "").strip()
    if not reason or len(reason) > 300:
        raise HTTPException(status_code=422, detail="举报理由长度应为 1-300 字")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT user_id FROM comments WHERE id = %s AND status = 'visible' LIMIT 1",
                (comment_id,),
            )
            comment = cursor.fetchone()
            if comment is None:
                raise HTTPException(status_code=404, detail="留言不存在")
            if comment["user_id"] == user["id"]:
                raise HTTPException(status_code=422, detail="不能举报自己的留言")
            cursor.execute(
                """
                INSERT INTO comment_reports (comment_id, reporter_id, reason)
                VALUES (%s, %s, %s)
                ON CONFLICT(comment_id, reporter_id) DO UPDATE SET
                  reason = excluded.reason,
                  status = 'pending'
                """,
                (comment_id, user["id"], reason),
            )
    return {"ok": True}


@router.get("/admin/comment-reports")
def admin_list_comment_reports(
    status: str = Query(default="pending", pattern="^(pending|resolved|dismissed)$"),
    _: dict[str, Any] = Depends(_require_admin),
):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT cr.*, c.content, c.target_type, c.target_id,
                       CASE WHEN author.deleted_at IS NOT NULL THEN '已注销用户' ELSE author.username END AS author_username,
                       CASE WHEN reporter.deleted_at IS NOT NULL THEN '已注销用户' ELSE reporter.username END AS reporter_username
                FROM comment_reports cr
                JOIN comments c ON c.id = cr.comment_id
                JOIN users author ON author.id = c.user_id
                JOIN users reporter ON reporter.id = cr.reporter_id
                WHERE cr.status = %s
                ORDER BY cr.created_at ASC, cr.id ASC
                """,
                (status,),
            )
            rows = cursor.fetchall()
    return {
        "data": [
            {
                "id": row["id"],
                "commentId": row["comment_id"],
                "content": row["content"],
                "targetType": row["target_type"],
                "targetId": row["target_id"],
                "authorUsername": row["author_username"],
                "reporterUsername": row["reporter_username"],
                "reason": row["reason"],
                "createdAt": row["created_at"],
            }
            for row in rows
        ]
    }


@router.patch("/admin/comment-reports/{report_id}")
def admin_review_comment_report(
    report_id: int,
    payload: dict[str, Any],
    admin: dict[str, Any] = Depends(_require_admin),
):
    status = str(payload.get("status") or "")
    hide_comment = bool(payload.get("hideComment"))
    if status not in {"resolved", "dismissed"}:
        raise HTTPException(status_code=422, detail="处理状态只能是 resolved 或 dismissed")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT comment_id FROM comment_reports WHERE id = %s AND status = 'pending' LIMIT 1",
                (report_id,),
            )
            report = cursor.fetchone()
            if report is None:
                raise HTTPException(status_code=404, detail="待处理举报不存在")
            if hide_comment:
                cursor.execute("UPDATE comments SET status = 'hidden' WHERE id = %s", (report["comment_id"],))
            cursor.execute(
                """
                UPDATE comment_reports
                SET status = %s, resolved_at = CURRENT_TIMESTAMP, resolved_by = %s
                WHERE id = %s
                """,
                (status, admin["id"], report_id),
            )
    return {"ok": True, "status": status}


@router.delete("/admin/comment-reports/{report_id}/content")
def admin_delete_reported_comment(
    report_id: int,
    admin: dict[str, Any] = Depends(_require_admin),
):
    """软删除被举报留言并处理该留言的全部待审举报。"""

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT comment_id
                FROM comment_reports
                WHERE id = %s AND status = 'pending'
                LIMIT 1
                """,
                (report_id,),
            )
            report = cursor.fetchone()
            if report is None:
                raise HTTPException(status_code=404, detail="待处理举报不存在")
            cursor.execute(
                "UPDATE comments SET content = '', status = 'deleted' WHERE id = %s",
                (report["comment_id"],),
            )
            cursor.execute(
                """
                UPDATE comment_reports
                SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP, resolved_by = %s
                WHERE comment_id = %s AND status = 'pending'
                """,
                (admin["id"], report["comment_id"]),
            )
    return {"ok": True, "commentId": report["comment_id"]}
