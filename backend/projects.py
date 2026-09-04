"""CAS 项目数据访问模块。

这里集中处理 projects 表的查询和数据格式化。路由层只负责接收 HTTP 参数和返回
响应，不直接关心 SQL 字段如何映射到前端字段。
"""

import json
import re
import secrets
from typing import Any, Literal

from backend.database import get_db_connection
from backend.media import public_media_url
from backend.project_assets import (
    ProjectAssetError,
    normalize_project_updates,
    project_icon_url,
    public_updates,
)
from backend.view_tracking import can_track_view, mark_view_tracked

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


def format_project(
    row: dict[str, Any],
    member_list: list[dict[str, Any]] | None = None,
    *,
    admin: bool = False,
) -> dict[str, Any]:
    """把数据库行转换为前端约定的 Project JSON。

    数据库字段使用 snake_case，前端接口使用更贴近 JavaScript 的 camelCase。
    这个转换层让数据库结构和前端展示结构保持解耦。
    """

    asset_dir = row.get("asset_dir")
    try:
        updates = (
            normalize_project_updates(row.get("updates"), asset_dir, allow_legacy=True)
            if admin
            else public_updates(row.get("updates"), asset_dir)
        )
    except ProjectAssetError:
        updates = parse_json_field(row.get("updates"))

    result = {
        "id": row["id"],
        "name": row["name"],
        "leader": row["leader"],
        "members": row["members"],
        "memberList": member_list or [],
        "category": row["category"],
        "year": row["year"],
        # Directory-derived icon first; unresolved legacy rows retain their old URL.
        "icon": project_icon_url(asset_dir, row.get("icon")),
        "description": row["description"],
        "media": parse_json_field(row.get("media")),
        "cas": {
            "creativity": bool(row.get("cas_creativity")),
            "activity": bool(row.get("cas_activity")),
            "service": bool(row.get("cas_service")),
        },
        "popularity": row.get("popularity", 0),
        "updates": updates,
        "createdAt": row.get("created_at"),
        "updatedAt": row.get("updated_at"),
    }
    if admin:
        result["assetDir"] = asset_dir
        result["assetDirWarning"] = None if asset_dir else "尚未配置项目资源目录"
    return result


def split_member_names(leader: str, members: str) -> list[str]:
    raw_names = [leader, *re.split(r"[,，、;\n]+", members or "")]
    result: list[str] = []
    seen: set[str] = set()
    for value in raw_names:
        name = str(value or "").strip()
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        result.append(name)
    return result


def list_project_members(project_id: int) -> list[dict[str, Any]]:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  pm.person_id,
                  pm.display_name_snapshot,
                  pm.role,
                  pm.sort_order,
                  pm.contact_type,
                  pm.contact_value,
                  p.avatar_url AS person_avatar_url,
                  p.user_id,
                  u.username,
                  u.display_name,
                  u.avatar_url AS user_avatar_url,
                  u.is_active
                FROM project_members pm
                JOIN people p ON p.id = pm.person_id
                LEFT JOIN users u ON u.id = p.user_id
                WHERE pm.project_id = %s
                ORDER BY
                  CASE pm.role WHEN 'leader' THEN 0 ELSE 1 END,
                  pm.sort_order ASC,
                  pm.person_id ASC
                """,
                (project_id,),
            )
            rows = cursor.fetchall()
    return [
        {
            "personId": row["person_id"],
            "name": row["display_name_snapshot"],
            "role": row["role"],
            "avatarUrl": public_media_url(row.get("user_avatar_url") or row.get("person_avatar_url")),
            "userId": row.get("user_id") if row.get("is_active") else None,
            "username": row.get("username") if row.get("is_active") else None,
            "registered": bool(row.get("user_id") and row.get("is_active")),
            "sortOrder": row.get("sort_order", 0),
            "contactType": row.get("contact_type"),
            "contactValue": row.get("contact_value"),
        }
        for row in rows
    ]


def project_update_publisher(
    project_id: int,
    user: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return the trusted publisher identity for a project member or admin.

    Membership is derived only from the administrator-maintained people binding;
    a matching display name or a client-provided member list never grants access.
    """

    if user is None:
        return None
    if user.get("role") == "admin":
        return {
            "userId": user["id"],
            "name": user.get("displayName") or user.get("username") or "管理员",
            "role": "admin",
        }

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT pm.person_id, pm.display_name_snapshot, pm.role
                FROM project_members pm
                JOIN people p ON p.id = pm.person_id
                WHERE pm.project_id = %s
                  AND p.user_id = %s
                  AND p.status <> 'archived'
                LIMIT 1
                """,
                (project_id, user["id"]),
            )
            membership = cursor.fetchone()
    if membership is None:
        return None
    return {
        "personId": membership["person_id"],
        "userId": user["id"],
        "name": membership["display_name_snapshot"],
        "role": membership["role"],
    }


def decorate_project_for_viewer(
    project: dict[str, Any],
    user: dict[str, Any] | None,
) -> dict[str, Any]:
    """Attach server-derived create/delete permissions to a project detail."""

    publisher = project_update_publisher(project["id"], user)
    project["viewerPermissions"] = {"canCreateUpdate": publisher is not None}
    can_delete_all = bool(publisher and publisher["role"] in {"admin", "leader"})
    publisher_person_id = publisher.get("personId") if publisher else None
    publisher_user_id = publisher["userId"] if publisher else None
    for update in project.get("updates", []):
        if not isinstance(update, dict):
            continue
        update["canDelete"] = can_delete_all or bool(
            (publisher_person_id and update.get("authorPersonId") == publisher_person_id)
            or (
                not update.get("authorPersonId")
                and publisher_user_id
                and update.get("authorUserId") == publisher_user_id
            )
        )
    return project


def _delete_unused_provisional_people(cursor: Any) -> None:
    cursor.execute(
        """
        DELETE FROM people
        WHERE status = 'provisional'
          AND user_id IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM project_members pm WHERE pm.person_id = people.id
          )
          AND NOT EXISTS (
            SELECT 1 FROM person_claims pc WHERE pc.person_id = people.id
          )
        """
    )


def sync_project_members(project_id: int, leader: str, members: str) -> None:
    """同步管理员维护的文本成员和结构化关系。

    同一个项目内按姓名复用既有档案；新名字创建项目级待绑定档案，绝不跨项目按姓名
    自动合并。
    """

    names = split_member_names(leader, members)
    leader_key = str(leader or "").strip().casefold()
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT pm.person_id, pm.display_name_snapshot
                FROM project_members pm
                WHERE pm.project_id = %s
                """,
                (project_id,),
            )
            existing = {
                row["display_name_snapshot"].strip().casefold(): row["person_id"]
                for row in cursor.fetchall()
            }
            retained_person_ids: list[int] = []
            for index, name in enumerate(names):
                person_id = existing.get(name.casefold())
                if person_id is None:
                    source_key = f"project:{project_id}:member:{secrets.token_hex(8)}"
                    cursor.execute(
                        """
                        INSERT INTO people (display_name, source_key, status)
                        VALUES (%s, %s, 'provisional')
                        """,
                        (name, source_key),
                    )
                    person_id = cursor.lastrowid
                retained_person_ids.append(person_id)
                cursor.execute(
                    """
                    INSERT INTO project_members
                      (project_id, person_id, role, display_name_snapshot, sort_order)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT(project_id, person_id) DO UPDATE SET
                      role = excluded.role,
                      display_name_snapshot = excluded.display_name_snapshot,
                      sort_order = excluded.sort_order
                    """,
                    (
                        project_id,
                        person_id,
                        "leader" if name.casefold() == leader_key else "member",
                        name,
                        index * 10,
                    ),
                )

            if retained_person_ids:
                placeholders = ", ".join(["%s"] * len(retained_person_ids))
                cursor.execute(
                    f"""
                    DELETE FROM project_members
                    WHERE project_id = %s AND person_id NOT IN ({placeholders})
                    """,
                    [project_id, *retained_person_ids],
                )
            else:
                cursor.execute("DELETE FROM project_members WHERE project_id = %s", (project_id,))

            _delete_unused_provisional_people(cursor)


def replace_project_members(project_id: int, members: list[dict[str, Any]]) -> None:
    """Replace a project's structured members, contacts, roles and ordering.

    Existing people are addressed by ``personId`` so approved claims and account
    bindings survive edits. New rows create project-scoped provisional people;
    names are never matched across projects.
    """

    if not members:
        raise ValueError("项目至少需要一名成员")
    leaders = [member for member in members if member.get("role") == "leader"]
    if len(leaders) > 1:
        raise ValueError("项目最多只能有一名负责人")

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
            if cursor.fetchone() is None:
                raise ValueError("项目不存在")
            cursor.execute(
                """
                SELECT pm.person_id
                FROM project_members pm
                WHERE pm.project_id = %s
                """,
                (project_id,),
            )
            existing_person_ids = {row["person_id"] for row in cursor.fetchall()}
            retained_person_ids: list[int] = []

            for index, member in enumerate(members):
                name = str(member.get("name") or "").strip()
                if not name:
                    raise ValueError("成员姓名不能为空")
                person_id = member.get("personId")
                if person_id is not None:
                    person_id = int(person_id)
                    if person_id not in existing_person_ids:
                        raise ValueError("成员档案不属于当前项目")
                    cursor.execute(
                        """
                        UPDATE people
                        SET display_name = %s
                        WHERE id = %s AND status = 'provisional' AND user_id IS NULL
                        """,
                        (name, person_id),
                    )
                else:
                    source_key = f"project:{project_id}:member:{secrets.token_hex(8)}"
                    cursor.execute(
                        """
                        INSERT INTO people (display_name, source_key, status)
                        VALUES (%s, %s, 'provisional')
                        """,
                        (name, source_key),
                    )
                    person_id = cursor.lastrowid

                retained_person_ids.append(person_id)
                cursor.execute(
                    """
                    INSERT INTO project_members
                      (project_id, person_id, role, display_name_snapshot, sort_order,
                       contact_type, contact_value)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(project_id, person_id) DO UPDATE SET
                      role = excluded.role,
                      display_name_snapshot = excluded.display_name_snapshot,
                      sort_order = excluded.sort_order,
                      contact_type = excluded.contact_type,
                      contact_value = excluded.contact_value
                    """,
                    (
                        project_id,
                        person_id,
                        member["role"],
                        name,
                        index * 10,
                        member.get("contactType"),
                        member.get("contactValue"),
                    ),
                )

            placeholders = ", ".join(["%s"] * len(retained_person_ids))
            cursor.execute(
                f"""
                DELETE FROM project_members
                WHERE project_id = %s AND person_id NOT IN ({placeholders})
                """,
                [project_id, *retained_person_ids],
            )

            leader_name = str(leaders[0]["name"]).strip() if leaders else ""
            member_summary = ", ".join(str(member["name"]).strip() for member in members)
            cursor.execute(
                "UPDATE projects SET leader = %s, members = %s WHERE id = %s",
                (leader_name, member_summary, project_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("项目不存在")
            _delete_unused_provisional_people(cursor)


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

    return [format_project(row) for row in rows]


def get_project(
    project_id: int,
    *,
    track_view: bool = False,
    viewer_user_id: int | None = None,
) -> dict[str, Any] | None:
    """按 ID 查询单个项目，并可累计公开详情浏览热度。"""

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            if track_view and can_track_view("project", project_id, viewer_user_id):
                cursor.execute(
                    "UPDATE projects SET popularity = popularity + 1 WHERE id = %s",
                    (project_id,),
                )
                if cursor.rowcount:
                    mark_view_tracked("project", project_id, viewer_user_id)
            cursor.execute("SELECT * FROM projects WHERE id = %s LIMIT 1", (project_id,))
            row = cursor.fetchone()

    return None if row is None else format_project(row, list_project_members(project_id))
