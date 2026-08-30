"""用户资料、关注、黑名单和管理员维护的 CAS 人员账号绑定接口。"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from backend.auth import format_user, get_current_user
from backend.avatars import delete_managed_avatar, store_avatar
from backend.database import get_db_connection

router = APIRouter(prefix="/api", tags=["social"])

MESSAGING_PERMISSIONS = {"everyone", "following", "mutual", "nobody"}


def _require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def _clean_optional_url(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("/") and not text.startswith("//"):
        return text
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail="头像地址只允许站内路径或 http/https URL")
    return text


def _ensure_active_user(cursor: Any, user_id: int) -> dict[str, Any]:
    cursor.execute("SELECT * FROM users WHERE id = %s AND is_active = 1 LIMIT 1", (user_id,))
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return row


def _public_profile(user_id: int, viewer_id: int | None = None) -> dict[str, Any]:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  u.*,
                  p.id AS person_id,
                  (SELECT COUNT(*) FROM user_follows f WHERE f.following_id = u.id) AS follower_count,
                  (SELECT COUNT(*) FROM user_follows f WHERE f.follower_id = u.id) AS following_count
                FROM users u
                LEFT JOIN people p ON p.user_id = u.id
                WHERE u.id = %s AND u.is_active = 1
                LIMIT 1
                """,
                (user_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="用户不存在")

            relationship = {
                "following": False,
                "followedBy": False,
                "blocked": False,
                "blockedBy": False,
            }
            if viewer_id is not None and viewer_id != user_id:
                cursor.execute(
                    """
                    SELECT
                      EXISTS(
                        SELECT 1 FROM user_follows
                        WHERE follower_id = %s AND following_id = %s
                      ) AS following,
                      EXISTS(
                        SELECT 1 FROM user_follows
                        WHERE follower_id = %s AND following_id = %s
                      ) AS followed_by,
                      EXISTS(
                        SELECT 1 FROM user_blocks
                        WHERE blocker_id = %s AND blocked_id = %s
                      ) AS blocked,
                      EXISTS(
                        SELECT 1 FROM user_blocks
                        WHERE blocker_id = %s AND blocked_id = %s
                      ) AS blocked_by
                    """,
                    (
                        viewer_id,
                        user_id,
                        user_id,
                        viewer_id,
                        viewer_id,
                        user_id,
                        user_id,
                        viewer_id,
                    ),
                )
                state = cursor.fetchone()
                relationship = {
                    "following": bool(state["following"]),
                    "followedBy": bool(state["followed_by"]),
                    "blocked": bool(state["blocked"]),
                    "blockedBy": bool(state["blocked_by"]),
                }

            cursor.execute(
                """
                SELECT p.id, p.name, p.year, pm.role
                FROM project_members pm
                JOIN projects p ON p.id = pm.project_id
                JOIN people person ON person.id = pm.person_id
                WHERE person.user_id = %s
                ORDER BY p.year DESC, p.id DESC
                """,
                (user_id,),
            )
            projects = [
                {
                    "id": project["id"],
                    "name": project["name"],
                    "year": project["year"],
                    "role": project["role"],
                }
                for project in cursor.fetchall()
            ]

    return {
        "id": row["id"],
        "username": row["username"],
        "displayName": row.get("display_name"),
        "avatarUrl": row.get("avatar_url"),
        "bio": row.get("bio") or "",
        "campusVerified": bool(row.get("campus_verified")),
        "linkedPersonId": row.get("person_id"),
        "followerCount": row.get("follower_count", 0),
        "followingCount": row.get("following_count", 0),
        "relationship": relationship,
        "projects": projects,
        "createdAt": row.get("created_at"),
    }


@router.get("/users")
def list_users(
    search: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=20, ge=1, le=50),
    user: dict[str, Any] = Depends(get_current_user),
):
    params: list[Any] = [user["id"]]
    where = ["u.is_active = 1", "u.id <> %s"]
    if search:
        keyword = f"%{search.strip()}%"
        where.append("(u.username LIKE %s OR u.display_name LIKE %s)")
        params.extend([keyword, keyword])
    params.append(limit)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT u.id, u.username, u.display_name, u.avatar_url, u.bio,
                       u.campus_verified, p.id AS person_id
                FROM users u
                LEFT JOIN people p ON p.user_id = u.id
                WHERE {' AND '.join(where)}
                ORDER BY u.campus_verified DESC, u.username ASC
                LIMIT %s
                """,
                params,
            )
            rows = cursor.fetchall()
    return {
        "data": [
            {
                "id": row["id"],
                "username": row["username"],
                "displayName": row.get("display_name"),
                "avatarUrl": row.get("avatar_url"),
                "bio": row.get("bio") or "",
                "campusVerified": bool(row.get("campus_verified")),
                "linkedPersonId": row.get("person_id"),
            }
            for row in rows
        ]
    }


@router.get("/users/{user_id}")
def user_profile(user_id: int, user: dict[str, Any] = Depends(get_current_user)):
    return {"data": _public_profile(user_id, user["id"])}


@router.patch("/users/me/profile")
def update_profile(payload: dict[str, Any], user: dict[str, Any] = Depends(get_current_user)):
    allowed = {"displayName", "avatarUrl", "bio", "messagingPermission"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise HTTPException(status_code=422, detail=f"字段不允许编辑：{', '.join(unknown)}")

    updates: list[str] = []
    params: list[Any] = []
    if "displayName" in payload:
        display_name = str(payload.get("displayName") or "").strip() or None
        if display_name and len(display_name) > 80:
            raise HTTPException(status_code=422, detail="姓名长度不能超过 80 位")
        updates.append("display_name = %s")
        params.append(display_name)
    if "avatarUrl" in payload:
        updates.append("avatar_url = %s")
        params.append(_clean_optional_url(payload.get("avatarUrl")))
    if "bio" in payload:
        bio = str(payload.get("bio") or "").strip()
        if len(bio) > 300:
            raise HTTPException(status_code=422, detail="个人简介不能超过 300 字")
        updates.append("bio = %s")
        params.append(bio)
    if "messagingPermission" in payload:
        permission = str(payload["messagingPermission"])
        if permission not in MESSAGING_PERMISSIONS:
            raise HTTPException(status_code=422, detail="私信权限设置无效")
        updates.append("messaging_permission = %s")
        params.append(permission)
    if not updates:
        raise HTTPException(status_code=422, detail="请求体不能为空")

    params.append(user["id"])
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = %s", params)
            cursor.execute(
                """
                SELECT u.*, p.id AS person_id
                FROM users u LEFT JOIN people p ON p.user_id = u.id
                WHERE u.id = %s
                """,
                (user["id"],),
            )
            row = cursor.fetchone()
    return format_user(row)


@router.post("/users/me/avatar")
async def upload_avatar(
    avatar: UploadFile = File(...),
    user: dict[str, Any] = Depends(get_current_user),
):
    new_url = await store_avatar(user["id"], avatar)
    old_url: str | None = None
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT avatar_url FROM users WHERE id = %s LIMIT 1", (user["id"],))
                current = cursor.fetchone()
                if current is None:
                    raise HTTPException(status_code=404, detail="用户不存在")
                old_url = current.get("avatar_url")
                cursor.execute("UPDATE users SET avatar_url = %s WHERE id = %s", (new_url, user["id"]))
                cursor.execute(
                    """
                    SELECT u.*, p.id AS person_id
                    FROM users u LEFT JOIN people p ON p.user_id = u.id
                    WHERE u.id = %s
                    """,
                    (user["id"],),
                )
                row = cursor.fetchone()
    except Exception:
        delete_managed_avatar(new_url)
        raise
    delete_managed_avatar(old_url)
    return format_user(row)


@router.delete("/users/me/avatar")
def remove_avatar(user: dict[str, Any] = Depends(get_current_user)):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT avatar_url FROM users WHERE id = %s LIMIT 1", (user["id"],))
            current = cursor.fetchone()
            if current is None:
                raise HTTPException(status_code=404, detail="用户不存在")
            old_url = current.get("avatar_url")
            cursor.execute("UPDATE users SET avatar_url = NULL WHERE id = %s", (user["id"],))
            cursor.execute(
                """
                SELECT u.*, p.id AS person_id
                FROM users u LEFT JOIN people p ON p.user_id = u.id
                WHERE u.id = %s
                """,
                (user["id"],),
            )
            row = cursor.fetchone()
    delete_managed_avatar(old_url)
    return format_user(row)


@router.post("/users/{user_id}/follow")
def follow_user(user_id: int, user: dict[str, Any] = Depends(get_current_user)):
    if user_id == user["id"]:
        raise HTTPException(status_code=422, detail="不能关注自己")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            _ensure_active_user(cursor, user_id)
            cursor.execute(
                """
                SELECT 1 FROM user_blocks
                WHERE (blocker_id = %s AND blocked_id = %s)
                   OR (blocker_id = %s AND blocked_id = %s)
                LIMIT 1
                """,
                (user["id"], user_id, user_id, user["id"]),
            )
            if cursor.fetchone() is not None:
                raise HTTPException(status_code=403, detail="黑名单关系下无法关注")
            cursor.execute(
                """
                INSERT INTO user_follows (follower_id, following_id)
                VALUES (%s, %s)
                ON CONFLICT(follower_id, following_id) DO NOTHING
                """,
                (user["id"], user_id),
            )
    return {"ok": True, "profile": _public_profile(user_id, user["id"])}


@router.delete("/users/{user_id}/follow")
def unfollow_user(user_id: int, user: dict[str, Any] = Depends(get_current_user)):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM user_follows WHERE follower_id = %s AND following_id = %s",
                (user["id"], user_id),
            )
    return {"ok": True}


@router.post("/users/{user_id}/block")
def block_user(user_id: int, user: dict[str, Any] = Depends(get_current_user)):
    if user_id == user["id"]:
        raise HTTPException(status_code=422, detail="不能拉黑自己")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            _ensure_active_user(cursor, user_id)
            cursor.execute(
                """
                INSERT INTO user_blocks (blocker_id, blocked_id)
                VALUES (%s, %s)
                ON CONFLICT(blocker_id, blocked_id) DO NOTHING
                """,
                (user["id"], user_id),
            )
            cursor.execute(
                """
                DELETE FROM user_follows
                WHERE (follower_id = %s AND following_id = %s)
                   OR (follower_id = %s AND following_id = %s)
                """,
                (user["id"], user_id, user_id, user["id"]),
            )
    return {"ok": True}


@router.delete("/users/{user_id}/block")
def unblock_user(user_id: int, user: dict[str, Any] = Depends(get_current_user)):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM user_blocks WHERE blocker_id = %s AND blocked_id = %s",
                (user["id"], user_id),
            )
    return {"ok": True}


@router.get("/people/{person_id}")
def person_detail(person_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT p.*, u.username, u.display_name AS user_display_name,
                       u.avatar_url AS user_avatar_url, u.is_active
                FROM people p
                LEFT JOIN users u ON u.id = p.user_id
                WHERE p.id = %s AND p.status <> 'archived'
                LIMIT 1
                """,
                (person_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="人员档案不存在")
            cursor.execute(
                """
                SELECT projects.id, projects.name, projects.year, pm.role
                FROM project_members pm
                JOIN projects ON projects.id = pm.project_id
                WHERE pm.person_id = %s
                ORDER BY projects.year DESC, projects.id DESC
                """,
                (person_id,),
            )
            projects = cursor.fetchall()
    linked = bool(row.get("user_id") and row.get("is_active"))
    return {
        "data": {
            "id": row["id"],
            "displayName": row["display_name"],
            "avatarUrl": row.get("user_avatar_url") or row.get("avatar_url"),
            "status": row["status"],
            "registered": linked,
            "user": (
                {
                    "id": row["user_id"],
                    "username": row.get("username"),
                    "displayName": row.get("user_display_name"),
                }
                if linked
                else None
            ),
            "projects": [
                {
                    "id": project["id"],
                    "name": project["name"],
                    "year": project["year"],
                    "role": project["role"],
                }
                for project in projects
            ],
        }
    }


@router.patch("/admin/projects/{project_id}/members/{person_id}/binding")
def bind_project_member(
    project_id: int,
    person_id: int,
    payload: dict[str, Any],
    admin: dict[str, Any] = Depends(_require_admin),
):
    raw_user_id = payload.get("userId")
    try:
        user_id = int(raw_user_id) if raw_user_id is not None else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="userId 无效") from None
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT p.*
                FROM people p
                JOIN project_members pm ON pm.person_id = p.id
                WHERE p.id = %s AND pm.project_id = %s
                LIMIT 1
                """,
                (person_id, project_id),
            )
            person = cursor.fetchone()
            if person is None:
                raise HTTPException(status_code=404, detail="项目成员不存在")
            if user_id is not None:
                _ensure_active_user(cursor, user_id)
                cursor.execute(
                    "SELECT id FROM people WHERE user_id = %s AND id <> %s LIMIT 1",
                    (user_id, person_id),
                )
                if cursor.fetchone() is not None:
                    raise HTTPException(status_code=409, detail="该账号已绑定其他人员档案")
            old_user_id = person.get("user_id")
            cursor.execute(
                "UPDATE people SET user_id = %s, status = %s WHERE id = %s",
                (user_id, "claimed" if user_id else "provisional", person_id),
            )
            if old_user_id is not None and old_user_id != user_id:
                cursor.execute(
                    """
                    UPDATE users
                    SET campus_verified = CASE
                      WHEN EXISTS(SELECT 1 FROM people WHERE user_id = users.id) THEN 1
                      ELSE 0
                    END
                    WHERE id = %s
                    """,
                    (old_user_id,),
                )
            if user_id is not None:
                cursor.execute("UPDATE users SET campus_verified = 1 WHERE id = %s", (user_id,))
                cursor.execute(
                    """
                    UPDATE person_claims
                    SET status = 'cancelled', reviewed_by = %s, reviewed_at = CURRENT_TIMESTAMP
                    WHERE person_id = %s AND status = 'pending'
                    """,
                    (admin["id"], person_id),
                )
    return {"ok": True}
