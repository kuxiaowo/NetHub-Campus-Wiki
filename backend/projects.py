"""CAS 项目数据访问模块。

这里集中处理 projects 表的查询和数据格式化。路由层只负责接收 HTTP 参数和返回
响应，不直接关心 SQL 字段如何映射到前端字段。
"""

import json
from typing import Any, Literal

from backend.database import get_db_connection

ProjectSort = Literal["latest", "popular"]


def parse_json_field(value: Any, default: list | dict | None = None) -> list | dict:
    """解析 MySQL JSON 字段。

    PyMySQL 读取 JSON 字段时可能返回字符串，也可能在某些场景下已经是 Python
    对象。这里统一兜底，避免前端收到 null 或非法结构。
    """

    fallback = [] if default is None else default
    if value is None:
        return fallback
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def format_project(row: dict[str, Any]) -> dict[str, Any]:
    """把数据库行转换为前端约定的 Project JSON。

    数据库字段使用 snake_case，前端接口使用更贴近 JavaScript 的 camelCase。
    这个转换层让数据库结构和前端展示结构保持解耦。
    """

    return {
        "id": row["id"],
        "name": row["name"],
        "leader": row["leader"],
        "members": row["members"],
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
            cursor.execute("SELECT DISTINCT category FROM projects ORDER BY category ASC")
            categories = [row["category"] for row in cursor.fetchall()]

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

    return [format_project(row) for row in rows]


def get_project(project_id: int) -> dict[str, Any] | None:
    """按 ID 查询单个项目；不存在时返回 None。"""

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM projects WHERE id = %s LIMIT 1", (project_id,))
            row = cursor.fetchone()

    return None if row is None else format_project(row)
