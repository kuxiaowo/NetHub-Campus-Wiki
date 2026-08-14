"""CAS 项目数据访问模块。

这里集中处理 projects 表的查询和数据格式化。路由层只负责接收 HTTP 参数和返回
响应，不直接关心 SQL 字段如何映射到前端字段。
"""

import json
import re
from typing import Any, Literal

from backend.database import Cursor, get_db_connection

ProjectSort = Literal["latest", "popular"]


def parse_json_field(value: Any, default: list | dict | None = None) -> list | dict:
    """把数据库中的 JSON 文本统一转换为列表或对象。"""

    fallback = [] if default is None else default
    if value is None:
        return fallback
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def format_project_member(row: dict[str, Any]) -> dict[str, Any]:
    linked_user = None
    if row.get("user_id") is not None:
        linked_user = {
            "id": row["user_id"],
            "username": row.get("linked_username"),
            "displayName": row.get("linked_display_name"),
        }
    return {
        "id": row["id"],
        "displayName": row["display_name"],
        "role": row["role"],
        "sortOrder": row.get("sort_order", 0),
        "user": linked_user,
    }


def _member_profiles_for_projects(project_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    if not project_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(project_ids))
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                  member.*,
                  linked_user.username AS linked_username,
                  linked_user.display_name AS linked_display_name
                FROM project_members member
                LEFT JOIN users linked_user ON linked_user.id = member.user_id
                WHERE member.project_id IN ({placeholders})
                ORDER BY member.project_id, member.sort_order, member.id
                """,
                project_ids,
            )
            rows = cursor.fetchall()
    result = {project_id: [] for project_id in project_ids}
    for row in rows:
        result.setdefault(row["project_id"], []).append(format_project_member(row))
    return result


def list_project_members(project_id: int) -> list[dict[str, Any]]:
    return _member_profiles_for_projects([project_id]).get(project_id, [])


def sync_project_members(
    cursor: Cursor,
    project_id: int,
    leader: str,
    members: str,
) -> None:
    """同步兼容字段与独立成员记录，并尽量保留已经建立的账号关联。"""

    desired: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add_member(name: str, role: str) -> None:
        clean_name = name.strip()
        key = clean_name.casefold()
        if not clean_name or key in seen:
            return
        seen.add(key)
        desired.append((clean_name, role))

    add_member(leader, "leader")
    for member_name in re.split(r"[,，、\n]", members or ""):
        add_member(member_name, "member")

    cursor.execute("SELECT * FROM project_members WHERE project_id = %s", (project_id,))
    existing_rows = cursor.fetchall()
    existing_by_name = {row["display_name"].strip().casefold(): row for row in existing_rows}
    retained_ids: list[int] = []

    for index, (display_name, role) in enumerate(desired):
        existing = existing_by_name.get(display_name.casefold())
        sort_order = index * 10
        if existing:
            cursor.execute(
                """
                UPDATE project_members
                SET display_name = %s, role = %s, sort_order = %s
                WHERE id = %s
                """,
                (display_name, role, sort_order, existing["id"]),
            )
            retained_ids.append(existing["id"])
        else:
            cursor.execute(
                """
                INSERT INTO project_members (project_id, display_name, role, sort_order)
                VALUES (%s, %s, %s, %s)
                """,
                (project_id, display_name, role, sort_order),
            )
            retained_ids.append(cursor.lastrowid)

    if retained_ids:
        placeholders = ", ".join(["%s"] * len(retained_ids))
        cursor.execute(
            f"DELETE FROM project_members WHERE project_id = %s AND id NOT IN ({placeholders})",
            [project_id, *retained_ids],
        )
    else:
        cursor.execute("DELETE FROM project_members WHERE project_id = %s", (project_id,))


def format_project(
    row: dict[str, Any],
    member_profiles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """把数据库行转换为前端约定的 Project JSON。

    数据库字段使用 snake_case，前端接口使用更贴近 JavaScript 的 camelCase。
    这个转换层让数据库结构和前端展示结构保持解耦。
    """

    return {
        "id": row["id"],
        "name": row["name"],
        "leader": row["leader"],
        "members": row["members"],
        "memberProfiles": member_profiles or [],
        "category": row["category"],
        "year": row["year"],
        "icon": row.get("icon") or "https://picsum.photos/seed/cas-project/300/300",
        "description": row["description"],
        "media": parse_json_field(row.get("media")),
        "cas": {
            "creativity": bool(row.get("cas_creativity")),
            "activity": bool(row.get("cas_activity")),
            "service": bool(row.get("cas_service")),
        },
        "popularity": row.get("popularity", 0),
        "updates": parse_json_field(row.get("updates")),
        "createdAt": row.get("created_at"),
        "updatedAt": row.get("updated_at"),
    }


def list_meta() -> dict[str, list[str] | list[int]]:
    """查询项目分类和年份，用于项目库筛选器。"""

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT name
                FROM project_categories
                WHERE is_active = 1
                ORDER BY sort_order ASC, id ASC
                """
            )
            categories = [row["name"] for row in cursor.fetchall()]

            cursor.execute("SELECT DISTINCT year FROM projects ORDER BY year DESC")
            years = [row["year"] for row in cursor.fetchall()]

    return {"categories": categories, "years": years}


def list_projects(
    category: str | None = None,
    year: int | None = None,
    search: str | None = None,
    sort: ProjectSort = "latest",
) -> list[dict[str, Any]]:
    """按筛选条件查询项目列表。

    SQL 条件和参数分开维护，所有用户输入都通过 cursor.execute 的参数绑定传入，
    避免手工拼接用户输入导致 SQL 注入。
    """

    where_parts = []
    params = []

    if category:
        where_parts.append("category = %s")
        params.append(category)
    if year:
        where_parts.append("year = %s")
        params.append(year)
    if search:
        where_parts.append("(name LIKE %s OR leader LIKE %s OR description LIKE %s)")
        keyword = f"%{search}%"
        params.extend([keyword, keyword, keyword])

    # sort 已在 FastAPI 查询参数中限制为 latest/popular，这里只切换白名单排序片段。
    order_by = "popularity DESC, created_at DESC" if sort == "popular" else "created_at DESC, id DESC"
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    sql = f"SELECT * FROM projects {where_sql} ORDER BY {order_by}"

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()

    member_profiles = _member_profiles_for_projects([row["id"] for row in rows])
    return [format_project(row, member_profiles.get(row["id"], [])) for row in rows]


def get_project(project_id: int) -> dict[str, Any] | None:
    """按 ID 查询单个项目；不存在时返回 None。"""

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM projects WHERE id = %s LIMIT 1", (project_id,))
            row = cursor.fetchone()

    return None if row is None else format_project(row, list_project_members(project_id))
