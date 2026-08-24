"""公告列表、详情和管理后台维护接口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.auth import get_current_user
from backend.database import get_db_connection

router = APIRouter(prefix="/api", tags=["announcements"])
ANNOUNCEMENT_STATUSES = {"draft", "published", "archived"}


def _require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def _announcement_dict(row: dict[str, Any], *, include_content: bool = False) -> dict[str, Any]:
    result = {
        "id": row["id"],
        "title": row["title"],
        "summary": row.get("summary") or "",
        "status": row["status"],
        "isPinned": bool(row.get("is_pinned")),
        "viewCount": int(row.get("view_count") or 0),
        "commentCount": int(row.get("comment_count") or 0),
        "publishedAt": row.get("published_at"),
        "createdAt": row.get("created_at"),
        "updatedAt": row.get("updated_at"),
    }
    if include_content:
        result["content"] = row["content"]
        result["author"] = (
            {
                "id": row.get("author_id"),
                "username": row.get("author_username"),
                "displayName": row.get("author_display_name"),
                "avatarUrl": row.get("author_avatar_url"),
            }
            if row.get("author_id")
            else None
        )
    return result


def _validate_payload(payload: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    allowed = {"title", "summary", "content", "status", "isPinned"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise HTTPException(status_code=422, detail=f"字段不允许编辑：{', '.join(unknown)}")
    if not partial:
        missing = [field for field in ("title", "content") if not str(payload.get(field) or "").strip()]
        if missing:
            raise HTTPException(status_code=422, detail=f"缺少字段：{', '.join(missing)}")

    normalized: dict[str, Any] = {}
    for field, max_length in (("title", 160), ("summary", 300), ("content", 20_000)):
        if field not in payload:
            continue
        value = str(payload.get(field) or "").strip()
        if field in {"title", "content"} and not value:
            raise HTTPException(status_code=422, detail=f"{field} 不能为空")
        if len(value) > max_length:
            raise HTTPException(status_code=422, detail=f"{field} 长度不能超过 {max_length}")
        normalized[field] = value
    if "status" in payload:
        status = str(payload["status"])
        if status not in ANNOUNCEMENT_STATUSES:
            raise HTTPException(status_code=422, detail="公告状态无效")
        normalized["status"] = status
    if "isPinned" in payload:
        normalized["isPinned"] = bool(payload["isPinned"])
    return normalized


@router.get("/announcements")
def list_announcements(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, alias="pageSize", ge=1, le=50),
    search: str | None = Query(default=None, max_length=100),
):
    where = ["a.status = 'published'", "a.published_at <= CURRENT_TIMESTAMP"]
    params: list[Any] = []
    if search:
        where.append("(a.title LIKE %s OR a.summary LIKE %s OR a.content LIKE %s)")
        keyword = f"%{search.strip()}%"
        params.extend([keyword, keyword, keyword])
    where_sql = " AND ".join(where)
    offset = (page - 1) * page_size
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS total FROM announcements a WHERE {where_sql}", params)
            total = cursor.fetchone()["total"]
            cursor.execute(
                f"""
                SELECT a.*,
                  (
                    SELECT COUNT(*) FROM comments c
                    WHERE c.target_type = 'announcement'
                      AND c.target_id = a.id
                      AND c.status = 'visible'
                  ) AS comment_count
                FROM announcements a
                WHERE {where_sql}
                ORDER BY a.is_pinned DESC, a.published_at DESC, a.id DESC
                LIMIT %s OFFSET %s
                """,
                [*params, page_size, offset],
            )
            rows = cursor.fetchall()
    return {
        "data": [_announcement_dict(row) for row in rows],
        "page": page,
        "pageSize": page_size,
        "total": total,
        "hasMore": offset + len(rows) < total,
    }


@router.get("/announcements/{announcement_id}")
def announcement_detail(
    announcement_id: int,
    track: bool = Query(default=True),
):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            if track:
                cursor.execute(
                    """
                    UPDATE announcements
                    SET view_count = view_count + 1
                    WHERE id = %s AND status = 'published' AND published_at <= CURRENT_TIMESTAMP
                    """,
                    (announcement_id,),
                )
            cursor.execute(
                """
                SELECT a.*,
                  u.id AS author_id,
                  u.username AS author_username,
                  u.display_name AS author_display_name,
                  u.avatar_url AS author_avatar_url,
                  (
                    SELECT COUNT(*) FROM comments c
                    WHERE c.target_type = 'announcement'
                      AND c.target_id = a.id
                      AND c.status = 'visible'
                  ) AS comment_count
                FROM announcements a
                LEFT JOIN users u ON u.id = a.created_by
                WHERE a.id = %s
                  AND a.status = 'published'
                  AND a.published_at <= CURRENT_TIMESTAMP
                LIMIT 1
                """,
                (announcement_id,),
            )
            row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="公告不存在")
    return {"data": _announcement_dict(row, include_content=True)}


@router.get("/admin/announcements")
def admin_list_announcements(_: dict[str, Any] = Depends(_require_admin)):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT a.*,
                  (
                    SELECT COUNT(*) FROM comments c
                    WHERE c.target_type = 'announcement'
                      AND c.target_id = a.id
                      AND c.status = 'visible'
                  ) AS comment_count
                FROM announcements a
                ORDER BY a.is_pinned DESC, a.created_at DESC, a.id DESC
                """
            )
            rows = cursor.fetchall()
    return {"data": [_announcement_dict(row, include_content=True) for row in rows]}


@router.post("/admin/announcements")
def admin_create_announcement(
    payload: dict[str, Any],
    admin: dict[str, Any] = Depends(_require_admin),
):
    data = _validate_payload(payload, partial=False)
    status = data.get("status", "published")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO announcements
                  (title, summary, content, status, is_pinned, created_by, published_at)
                VALUES (%s, %s, %s, %s, %s, %s,
                  CASE WHEN %s = 'published' THEN CURRENT_TIMESTAMP ELSE NULL END)
                """,
                (
                    data["title"],
                    data.get("summary", ""),
                    data["content"],
                    status,
                    1 if data.get("isPinned") else 0,
                    admin["id"],
                    status,
                ),
            )
            announcement_id = cursor.lastrowid
    return {"data": {"id": announcement_id}}


@router.patch("/admin/announcements/{announcement_id}")
def admin_update_announcement(
    announcement_id: int,
    payload: dict[str, Any],
    _: dict[str, Any] = Depends(_require_admin),
):
    data = _validate_payload(payload, partial=True)
    if not data:
        raise HTTPException(status_code=422, detail="请求体不能为空")
    column_map = {
        "title": "title",
        "summary": "summary",
        "content": "content",
        "status": "status",
        "isPinned": "is_pinned",
    }
    updates: list[str] = []
    params: list[Any] = []
    for field, value in data.items():
        updates.append(f"{column_map[field]} = %s")
        params.append(1 if field == "isPinned" and value else 0 if field == "isPinned" else value)
    if data.get("status") == "published":
        updates.append("published_at = COALESCE(published_at, CURRENT_TIMESTAMP)")
    params.append(announcement_id)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"UPDATE announcements SET {', '.join(updates)} WHERE id = %s", params)
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="公告不存在")
    return {"ok": True}


@router.delete("/admin/announcements/{announcement_id}")
def admin_archive_announcement(
    announcement_id: int,
    _: dict[str, Any] = Depends(_require_admin),
):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE announcements SET status = 'archived' WHERE id = %s",
                (announcement_id,),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="公告不存在")
    return {"ok": True}
