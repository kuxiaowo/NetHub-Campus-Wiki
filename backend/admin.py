"""Admin API routes and data access helpers.

The admin module keeps privileged write operations away from the public read
routes. Every route in this file requires an authenticated admin user.
"""

from __future__ import annotations

import json
import re
import secrets
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pymysql.err import IntegrityError

from backend.auth import (
    create_user,
    format_user,
    get_current_user,
    hash_password,
    validate_password,
    validate_username,
)
from backend.database import get_db_connection
from backend.projects import format_project
from backend.resources import format_resource

router = APIRouter(prefix="/api/admin", tags=["admin"])

BASE_DIR = Path(__file__).resolve().parents[1]
PUBLIC_DIR = BASE_DIR / "public"
UPLOAD_DIR = PUBLIC_DIR / "uploads"
ALLOWED_UPLOAD_EXTENSIONS = {
    "jpg",
    "jpeg",
    "png",
    "webp",
    "gif",
    "pdf",
    "doc",
    "docx",
    "ppt",
    "pptx",
    "xls",
    "xlsx",
    "zip",
}

ALLOWED_DB_TABLES = {
    "users",
    "projects",
    "project_categories",
    "resource_categories",
    "resources",
    "photo_activities",
    "photo_items",
}
HIDDEN_FIELDS = {"users": {"password_hash"}}
READONLY_FIELDS = {"id", "created_at", "updated_at"}
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")
WINDOWS_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:/")


def require_admin_user(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Allow only active admin users to access admin routes."""

    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def _ensure_table(table: str) -> str:
    if table not in ALLOWED_DB_TABLES:
        raise HTTPException(status_code=404, detail="表不存在或不允许访问")
    return table


def _ensure_identifier(value: str) -> str:
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise HTTPException(status_code=422, detail="字段名不合法")
    return value


def _public_relative_path(value: str | None) -> str:
    original_value = (value or "").strip().replace("\\", "/")
    original_path = Path(original_value)
    if (
        original_value.startswith("/")
        or WINDOWS_DRIVE_PATTERN.match(original_value)
        or original_path.is_absolute()
        or original_path.drive
    ):
        raise HTTPException(status_code=422, detail="public 路径不合法")
    raw_value = original_value.strip("/")
    if not raw_value:
        return ""
    raw_path = Path(raw_value)
    if raw_path.is_absolute() or raw_path.drive or ".." in raw_path.parts:
        raise HTTPException(status_code=422, detail="public 路径不合法")
    return raw_value


def _resolve_public_path(value: str | None) -> tuple[Path, str]:
    relative = _public_relative_path(value)
    target = (PUBLIC_DIR / relative).resolve()
    public_root = PUBLIC_DIR.resolve()
    if target != public_root and public_root not in target.parents:
        raise HTTPException(status_code=422, detail="public 路径不合法")
    return target, relative


def _file_url(relative_path: str, is_dir: bool = False) -> str:
    if not relative_path:
        return "/"
    suffix = "/" if is_dir and not relative_path.endswith("/") else ""
    return f"/{relative_path}{suffix}"


def _format_file_item(path: Path, root: Path) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    is_dir = path.is_dir()
    stat = path.stat()
    return {
        "name": path.name,
        "path": relative,
        "url": _file_url(relative, is_dir=is_dir),
        "type": "folder" if is_dir else "file",
        "size": None if is_dir else stat.st_size,
        "updatedAt": stat.st_mtime,
    }


def _visible_columns(table: str) -> list[dict[str, Any]]:
    table = _ensure_table(table)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  COLUMN_NAME AS name,
                  DATA_TYPE AS data_type,
                  COLUMN_TYPE AS column_type,
                  IS_NULLABLE AS is_nullable,
                  COLUMN_KEY AS column_key,
                  EXTRA AS extra
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                ORDER BY ORDINAL_POSITION
                """,
                (table,),
            )
            rows = cursor.fetchall()

    hidden = HIDDEN_FIELDS.get(table, set())
    return [
        {
            "name": row["name"],
            "dataType": row["data_type"],
            "columnType": row["column_type"],
            "nullable": row["is_nullable"] == "YES",
            "primaryKey": row["column_key"] == "PRI",
            "readonly": row["name"] in READONLY_FIELDS
            or "auto_increment" in str(row.get("extra") or ""),
        }
        for row in rows
        if row["name"] not in hidden
    ]


def _editable_column_names(table: str) -> set[str]:
    return {
        column["name"]
        for column in _visible_columns(table)
        if not column["readonly"]
    }


def _filter_payload(table: str, payload: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    editable = _editable_column_names(table)
    unknown = sorted(set(payload) - editable)
    if unknown:
        raise HTTPException(status_code=422, detail=f"字段不允许编辑：{', '.join(unknown)}")
    if not partial and not payload:
        raise HTTPException(status_code=422, detail="请求体不能为空")
    return payload


def _normalize_int(value: Any, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{field_name} 必须是数字") from None


def _ensure_row_exists(cursor: Any, table: str, row_id: int, detail: str) -> None:
    table = _ensure_identifier(table)
    cursor.execute(f"SELECT id FROM `{table}` WHERE id = %s LIMIT 1", (row_id,))
    if cursor.fetchone() is None:
        raise HTTPException(status_code=404, detail=detail)


def _fetch_resource(resource_id: int) -> dict[str, Any]:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM resources WHERE id = %s LIMIT 1", (resource_id,))
            row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="资源不存在")
    return format_resource(row)


def _fetch_project(project_id: int) -> dict[str, Any]:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM projects WHERE id = %s LIMIT 1", (project_id,))
            row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return format_project(row)


def _format_photo_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "activityId": row["activity_id"],
        "title": row["title"],
        "src": row["image_url"],
        "sortOrder": row["sort_order"],
        "createdAt": row.get("created_at"),
    }


def _format_activity(row: dict[str, Any]) -> dict[str, Any]:
    directory_count = _scan_public_photo_count(row.get("photo_dir"))
    return {
        "id": row["id"],
        "activity": row["activity"],
        "description": row["description"],
        "year": row["year"],
        "hot": row["hot"],
        "sortOrder": row.get("sort_order", 0),
        "photoDir": row.get("photo_dir"),
        "photoCount": directory_count or row.get("photo_count", 0),
        "createdAt": row.get("created_at"),
        "updatedAt": row.get("updated_at"),
    }


def _normalize_public_url(value: Any) -> str | None:
    raw_value = str(value or "").strip().replace("\\", "/")
    if not raw_value:
        return None
    if "://" in raw_value or WINDOWS_DRIVE_PATTERN.match(raw_value):
        raise HTTPException(status_code=422, detail="目录必须是 public 内的相对 URL")
    relative = raw_value.strip("/")
    raw_path = Path(relative)
    if raw_path.is_absolute() or raw_path.drive or ".." in raw_path.parts:
        raise HTTPException(status_code=422, detail="目录必须位于 public 内")
    target = (PUBLIC_DIR.resolve() / relative).resolve()
    public_root = PUBLIC_DIR.resolve()
    if target != public_root and public_root not in target.parents:
        raise HTTPException(status_code=422, detail="目录必须位于 public 内")
    return "/" if not relative else f"/{relative.rstrip('/')}/"


def _scan_public_photo_count(photo_dir: str | None) -> int:
    normalized = _normalize_public_url(photo_dir)
    if not normalized or normalized == "/":
        return 0
    target = (PUBLIC_DIR.resolve() / normalized.strip("/")).resolve()
    if not target.exists() or not target.is_dir():
        return 0
    return sum(
        1
        for item in target.iterdir()
        if item.is_file() and item.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    )


def _format_resource_category(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "value": row["value"],
        "label": row["label"],
        "sortOrder": row["sort_order"],
        "isActive": bool(row["is_active"]),
        "createdAt": row.get("created_at"),
        "updatedAt": row.get("updated_at"),
    }


def _format_project_category(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "sortOrder": row["sort_order"],
        "isActive": bool(row["is_active"]),
        "createdAt": row.get("created_at"),
        "updatedAt": row.get("updated_at"),
    }


def _json_list(value: Any, field_name: str) -> str:
    items = value if isinstance(value, list) else []
    clean_items = [str(item).strip() for item in items if str(item).strip()]
    return json.dumps(clean_items, ensure_ascii=False)


def _normalize_bool(value: Any) -> int:
    return 1 if value is True or str(value).lower() in {"1", "true", "yes", "on"} else 0


def _ensure_project_category(cursor: Any, category: str) -> None:
    clean_category = str(category or "").strip()
    if not clean_category:
        return
    cursor.execute("SELECT id FROM project_categories WHERE name = %s LIMIT 1", (clean_category,))
    if cursor.fetchone() is not None:
        return
    cursor.execute("SELECT COALESCE(MAX(sort_order), 0) + 10 AS next_sort_order FROM project_categories")
    next_sort_order = cursor.fetchone()["next_sort_order"]
    cursor.execute(
        """
        INSERT INTO project_categories (name, sort_order, is_active)
        VALUES (%s, %s, 1)
        """,
        (clean_category, next_sort_order),
    )


def _next_activity_sort_order(cursor: Any) -> int:
    cursor.execute("SELECT COALESCE(MAX(sort_order), 0) + 10 AS next_sort_order FROM photo_activities")
    return cursor.fetchone()["next_sort_order"]


def _normalize_reorder_items(payload: dict[str, Any]) -> list[dict[str, int]]:
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=422, detail="items 不能为空")
    normalized = []
    seen_ids = set()
    for item in items:
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail="items 格式不正确")
        item_id = _normalize_int(item.get("id"), "id")
        sort_order = _normalize_int(item.get("sortOrder"), "sortOrder")
        if item_id in seen_ids:
            raise HTTPException(status_code=422, detail="items 不能包含重复 ID")
        seen_ids.add(item_id)
        normalized.append({"id": item_id, "sortOrder": sort_order})
    return normalized


def _apply_reorder(cursor: Any, table: str, items: list[dict[str, int]], missing_detail: str) -> None:
    table = _ensure_identifier(table)
    ids = [item["id"] for item in items]
    placeholders = ", ".join(["%s"] * len(ids))
    cursor.execute(f"SELECT id FROM `{table}` WHERE id IN ({placeholders})", ids)
    found_ids = {row["id"] for row in cursor.fetchall()}
    missing_ids = sorted(set(ids) - found_ids)
    if missing_ids:
        raise HTTPException(status_code=404, detail=f"{missing_detail}: {', '.join(map(str, missing_ids))}")
    for item in items:
        cursor.execute(
            f"UPDATE `{table}` SET sort_order = %s WHERE id = %s",
            (item["sortOrder"], item["id"]),
        )


@router.get("/resource-categories")
def admin_list_resource_categories(_: dict[str, Any] = Depends(require_admin_user)):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM resource_categories
                ORDER BY sort_order ASC, id ASC
                """
            )
            rows = cursor.fetchall()
    return {"data": [_format_resource_category(row) for row in rows]}


@router.patch("/resource-categories/reorder")
def admin_reorder_resource_categories(
    payload: dict[str, Any],
    _: dict[str, Any] = Depends(require_admin_user),
):
    items = _normalize_reorder_items(payload)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            _apply_reorder(cursor, "resource_categories", items, "资源分类不存在")
    return {"ok": True}


@router.get("/project-categories")
def admin_list_project_categories(_: dict[str, Any] = Depends(require_admin_user)):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM project_categories
                ORDER BY sort_order ASC, id ASC
                """
            )
            rows = cursor.fetchall()
    return {"data": [_format_project_category(row) for row in rows]}


@router.patch("/project-categories/reorder")
def admin_reorder_project_categories(
    payload: dict[str, Any],
    _: dict[str, Any] = Depends(require_admin_user),
):
    items = _normalize_reorder_items(payload)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            _apply_reorder(cursor, "project_categories", items, "项目分类不存在")
    return {"ok": True}


@router.get("/projects")
def admin_list_projects(
    search: str | None = Query(default=None),
    category: str | None = Query(default=None),
    year: int | None = Query(default=None),
    sort: str = Query(default="latest", pattern="^(latest|popular)$"),
    _: dict[str, Any] = Depends(require_admin_user),
):
    params: list[Any] = []
    where_parts: list[str] = []
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
    order_by = "popularity DESC, created_at DESC" if sort == "popular" else "created_at DESC, id DESC"
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT * FROM projects {where_sql} ORDER BY {order_by}", params)
            rows = cursor.fetchall()
    return {"data": [format_project(row) for row in rows]}


@router.post("/projects")
def admin_create_project(payload: dict[str, Any], _: dict[str, Any] = Depends(require_admin_user)):
    required = ["name", "leader", "members", "category", "year", "description"]
    missing = [field for field in required if payload.get(field) in {None, ""}]
    if missing:
        raise HTTPException(status_code=422, detail=f"缺少字段：{', '.join(missing)}")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            _ensure_project_category(cursor, payload["category"])
            cursor.execute(
                """
                INSERT INTO projects
                  (name, leader, members, category, year, icon, description, media,
                   cas_creativity, cas_activity, cas_service, popularity, updates)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    payload["name"],
                    payload["leader"],
                    payload["members"],
                    payload["category"],
                    _normalize_int(payload["year"], "year"),
                    payload.get("icon") or None,
                    payload["description"],
                    _json_list(payload.get("media"), "media"),
                    _normalize_bool(payload.get("casCreativity")),
                    _normalize_bool(payload.get("casActivity")),
                    _normalize_bool(payload.get("casService")),
                    _normalize_int(payload.get("popularity", 0), "popularity"),
                    _json_list(payload.get("updates"), "updates"),
                ),
            )
            project_id = cursor.lastrowid
    return _fetch_project(project_id)


@router.patch("/projects/{project_id}")
def admin_update_project(
    project_id: int,
    payload: dict[str, Any],
    _: dict[str, Any] = Depends(require_admin_user),
):
    field_map = {
        "name": "name",
        "leader": "leader",
        "members": "members",
        "category": "category",
        "year": "year",
        "icon": "icon",
        "description": "description",
        "media": "media",
        "casCreativity": "cas_creativity",
        "casActivity": "cas_activity",
        "casService": "cas_service",
        "popularity": "popularity",
        "updates": "updates",
    }
    unknown = sorted(set(payload) - set(field_map))
    if unknown:
        raise HTTPException(status_code=422, detail=f"字段不允许编辑：{', '.join(unknown)}")
    updates = []
    params: list[Any] = []
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            if "category" in payload:
                _ensure_project_category(cursor, payload["category"])
            for api_field, column in field_map.items():
                if api_field not in payload:
                    continue
                value = payload[api_field]
                if api_field in {"year", "popularity"}:
                    value = _normalize_int(value, api_field)
                if api_field in {"casCreativity", "casActivity", "casService"}:
                    value = _normalize_bool(value)
                if api_field in {"media", "updates"}:
                    value = _json_list(value, api_field)
                if api_field == "icon" and value == "":
                    value = None
                updates.append(f"{column} = %s")
                params.append(value)
            if not updates:
                raise HTTPException(status_code=422, detail="请求体不能为空")
            params.append(project_id)
            cursor.execute(f"UPDATE projects SET {', '.join(updates)} WHERE id = %s", params)
            if cursor.rowcount == 0:
                _ensure_row_exists(cursor, "projects", project_id, "项目不存在")
    return _fetch_project(project_id)


@router.get("/users")
def admin_list_users(
    search: str | None = Query(default=None),
    role: str | None = Query(default=None, pattern="^(admin|user)$"),
    is_active: bool | None = Query(default=None, alias="isActive"),
    _: dict[str, Any] = Depends(require_admin_user),
):
    where_parts = []
    params: list[Any] = []
    if search:
        where_parts.append("(username LIKE %s OR display_name LIKE %s)")
        keyword = f"%{search}%"
        params.extend([keyword, keyword])
    if role:
        where_parts.append("role = %s")
        params.append(role)
    if is_active is not None:
        where_parts.append("is_active = %s")
        params.append(1 if is_active else 0)

    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM users {where_sql} ORDER BY created_at DESC, id DESC",
                params,
            )
            rows = cursor.fetchall()
    return {"data": [format_user(row) for row in rows]}


@router.post("/users")
def admin_create_user(payload: dict[str, Any], _: dict[str, Any] = Depends(require_admin_user)):
    username = str(payload.get("username") or "")
    password = str(payload.get("password") or "")
    role = payload.get("role") or "user"
    if role not in {"admin", "user"}:
        raise HTTPException(status_code=422, detail="角色只能是 admin 或 user")
    user = create_user(
        username=username,
        password=password,
        display_name=payload.get("displayName"),
    )
    if role != "user" or payload.get("isActive") is False:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE users
                    SET role = %s, is_active = %s
                    WHERE id = %s
                    """,
                    (role, 1 if payload.get("isActive", True) else 0, user["id"]),
                )
                cursor.execute("SELECT * FROM users WHERE id = %s", (user["id"],))
                row = cursor.fetchone()
        return format_user(row)
    return user


@router.patch("/users/{user_id}")
def admin_update_user(
    user_id: int,
    payload: dict[str, Any],
    _: dict[str, Any] = Depends(require_admin_user),
):
    allowed = {"role", "isActive"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise HTTPException(status_code=422, detail=f"字段不允许编辑：{', '.join(unknown)}")

    updates = []
    params: list[Any] = []
    if "role" in payload:
        if payload["role"] not in {"admin", "user"}:
            raise HTTPException(status_code=422, detail="角色只能是 admin 或 user")
        updates.append("role = %s")
        params.append(payload["role"])
    if "isActive" in payload:
        updates.append("is_active = %s")
        params.append(1 if payload["isActive"] else 0)
    if not updates:
        raise HTTPException(status_code=422, detail="请求体不能为空")

    params.append(user_id)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = %s", params)
            if cursor.rowcount == 0:
                _ensure_row_exists(cursor, "users", user_id, "用户不存在")
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            row = cursor.fetchone()
    return format_user(row)


@router.get("/resources")
def admin_list_resources(
    search: str | None = Query(default=None),
    category: str | None = Query(default=None),
    year: int | None = Query(default=None),
    _: dict[str, Any] = Depends(require_admin_user),
):
    params: list[Any] = []
    where_parts: list[str] = []
    if category:
        where_parts.append("category = %s")
        params.append(category)
    if year:
        where_parts.append("year = %s")
        params.append(year)
    if search:
        where_parts.append("(title LIKE %s OR description LIKE %s OR label LIKE %s OR type LIKE %s)")
        keyword = f"%{search}%"
        params.extend([keyword, keyword, keyword, keyword])
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT * FROM resources {where_sql} ORDER BY id DESC", params)
            rows = cursor.fetchall()
    return {"data": [format_resource(row) for row in rows]}


@router.post("/resources")
def admin_create_resource(payload: dict[str, Any], _: dict[str, Any] = Depends(require_admin_user)):
    required = ["title", "description", "year", "category", "label", "type", "image", "resourceUrl"]
    missing = [field for field in required if payload.get(field) in {None, ""}]
    if missing:
        raise HTTPException(status_code=422, detail=f"缺少字段：{', '.join(missing)}")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO resources
                  (title, description, year, category, label, type, hot, downloads, image, resource_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    payload["title"],
                    payload["description"],
                    _normalize_int(payload["year"], "year"),
                    payload["category"],
                    payload["label"],
                    payload["type"],
                    _normalize_int(payload.get("hot", 0), "hot"),
                    _normalize_int(payload.get("downloads", 0), "downloads"),
                    payload["image"],
                    payload["resourceUrl"],
                ),
            )
            resource_id = cursor.lastrowid
    return _fetch_resource(resource_id)


@router.patch("/resources/{resource_id}")
def admin_update_resource(
    resource_id: int,
    payload: dict[str, Any],
    _: dict[str, Any] = Depends(require_admin_user),
):
    field_map = {
        "title": "title",
        "description": "description",
        "year": "year",
        "category": "category",
        "label": "label",
        "type": "type",
        "hot": "hot",
        "downloads": "downloads",
        "image": "image",
        "resourceUrl": "resource_url",
    }
    unknown = sorted(set(payload) - set(field_map))
    if unknown:
        raise HTTPException(status_code=422, detail=f"字段不允许编辑：{', '.join(unknown)}")
    updates = []
    params: list[Any] = []
    for api_field, column in field_map.items():
        if api_field in payload:
            value = payload[api_field]
            if api_field in {"year", "hot", "downloads"}:
                value = _normalize_int(value, api_field)
            updates.append(f"{column} = %s")
            params.append(value)
    if not updates:
        raise HTTPException(status_code=422, detail="请求体不能为空")
    params.append(resource_id)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"UPDATE resources SET {', '.join(updates)} WHERE id = %s", params)
            if cursor.rowcount == 0:
                _ensure_row_exists(cursor, "resources", resource_id, "资源不存在")
    return _fetch_resource(resource_id)


@router.delete("/resources/{resource_id}")
def admin_delete_resource(resource_id: int, _: dict[str, Any] = Depends(require_admin_user)):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM resources WHERE id = %s", (resource_id,))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="资源不存在")
    return {"ok": True}


@router.get("/photo-activities")
def admin_list_photo_activities(
    search: str | None = Query(default=None),
    year: int | None = Query(default=None),
    _: dict[str, Any] = Depends(require_admin_user),
):
    params: list[Any] = []
    where_parts: list[str] = []
    if year:
        where_parts.append("pa.year = %s")
        params.append(year)
    if search:
        where_parts.append("(pa.activity LIKE %s OR pa.description LIKE %s)")
        keyword = f"%{search}%"
        params.extend([keyword, keyword])
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT pa.*, COUNT(pi.id) AS photo_count
                FROM photo_activities pa
                LEFT JOIN photo_items pi ON pi.activity_id = pa.id
                {where_sql}
                GROUP BY pa.id, pa.activity, pa.description, pa.year, pa.hot, pa.sort_order, pa.photo_dir, pa.created_at, pa.updated_at
                ORDER BY pa.sort_order ASC, pa.id DESC
                """,
                params,
            )
            rows = cursor.fetchall()
    return {"data": [_format_activity(row) for row in rows]}


@router.post("/photo-activities")
def admin_create_photo_activity(
    payload: dict[str, Any],
    _: dict[str, Any] = Depends(require_admin_user),
):
    required = ["activity", "description", "year"]
    missing = [field for field in required if payload.get(field) in {None, ""}]
    if missing:
        raise HTTPException(status_code=422, detail=f"缺少字段：{', '.join(missing)}")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO photo_activities (activity, description, year, hot, sort_order, photo_dir)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    payload["activity"],
                    payload["description"],
                    _normalize_int(payload["year"], "year"),
                    _normalize_int(payload.get("hot", 0), "hot"),
                    _normalize_int(payload.get("sortOrder", _next_activity_sort_order(cursor)), "sortOrder"),
                    _normalize_public_url(payload.get("photoDir")),
                ),
            )
            activity_id = cursor.lastrowid
            cursor.execute("SELECT *, 0 AS photo_count FROM photo_activities WHERE id = %s", (activity_id,))
            row = cursor.fetchone()
    return _format_activity(row)


@router.patch("/photo-activities/reorder")
def admin_reorder_photo_activities(
    payload: dict[str, Any],
    _: dict[str, Any] = Depends(require_admin_user),
):
    items = _normalize_reorder_items(payload)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            _apply_reorder(cursor, "photo_activities", items, "活动不存在")
    return {"ok": True}


@router.patch("/photo-activities/{activity_id}")
def admin_update_photo_activity(
    activity_id: int,
    payload: dict[str, Any],
    _: dict[str, Any] = Depends(require_admin_user),
):
    field_map = {
        "activity": "activity",
        "description": "description",
        "year": "year",
        "hot": "hot",
        "sortOrder": "sort_order",
        "photoDir": "photo_dir",
    }
    unknown = sorted(set(payload) - set(field_map))
    if unknown:
        raise HTTPException(status_code=422, detail=f"字段不允许编辑：{', '.join(unknown)}")
    updates = []
    params: list[Any] = []
    for api_field, column in field_map.items():
        if api_field in payload:
            value = payload[api_field]
            if api_field in {"year", "hot", "sortOrder"}:
                value = _normalize_int(value, api_field)
            if api_field == "photoDir":
                value = _normalize_public_url(value)
            updates.append(f"{column} = %s")
            params.append(value)
    if not updates:
        raise HTTPException(status_code=422, detail="请求体不能为空")
    params.append(activity_id)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"UPDATE photo_activities SET {', '.join(updates)} WHERE id = %s", params)
            if cursor.rowcount == 0:
                _ensure_row_exists(cursor, "photo_activities", activity_id, "活动不存在")
            cursor.execute(
                """
                SELECT pa.*, COUNT(pi.id) AS photo_count
                FROM photo_activities pa
                LEFT JOIN photo_items pi ON pi.activity_id = pa.id
                WHERE pa.id = %s
                GROUP BY pa.id, pa.activity, pa.description, pa.year, pa.hot, pa.sort_order, pa.photo_dir, pa.created_at, pa.updated_at
                """,
                (activity_id,),
            )
            row = cursor.fetchone()
    return _format_activity(row)


@router.delete("/photo-activities/{activity_id}")
def admin_delete_photo_activity(activity_id: int, _: dict[str, Any] = Depends(require_admin_user)):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM photo_activities WHERE id = %s", (activity_id,))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="活动不存在")
    return {"ok": True}


@router.get("/photo-activities/{activity_id}/photos")
def admin_list_photos(activity_id: int, _: dict[str, Any] = Depends(require_admin_user)):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM photo_activities WHERE id = %s", (activity_id,))
            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="活动不存在")
            cursor.execute(
                """
                SELECT *
                FROM photo_items
                WHERE activity_id = %s
                ORDER BY sort_order ASC, id ASC
                """,
                (activity_id,),
            )
            rows = cursor.fetchall()
    return {"data": [_format_photo_item(row) for row in rows]}


@router.post("/photo-activities/{activity_id}/photos")
def admin_create_photo(
    activity_id: int,
    payload: dict[str, Any],
    _: dict[str, Any] = Depends(require_admin_user),
):
    required = ["title", "src"]
    missing = [field for field in required if payload.get(field) in {None, ""}]
    if missing:
        raise HTTPException(status_code=422, detail=f"缺少字段：{', '.join(missing)}")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM photo_activities WHERE id = %s", (activity_id,))
            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="活动不存在")
            cursor.execute(
                """
                INSERT INTO photo_items (activity_id, title, image_url, sort_order)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    activity_id,
                    payload["title"],
                    payload["src"],
                    _normalize_int(payload.get("sortOrder", 0), "sortOrder"),
                ),
            )
            photo_id = cursor.lastrowid
            cursor.execute("SELECT * FROM photo_items WHERE id = %s", (photo_id,))
            row = cursor.fetchone()
    return _format_photo_item(row)


@router.patch("/photos/{photo_id}")
def admin_update_photo(
    photo_id: int,
    payload: dict[str, Any],
    _: dict[str, Any] = Depends(require_admin_user),
):
    field_map = {"title": "title", "src": "image_url", "sortOrder": "sort_order"}
    unknown = sorted(set(payload) - set(field_map))
    if unknown:
        raise HTTPException(status_code=422, detail=f"字段不允许编辑：{', '.join(unknown)}")
    updates = []
    params: list[Any] = []
    for api_field, column in field_map.items():
        if api_field in payload:
            value = payload[api_field]
            if api_field == "sortOrder":
                value = _normalize_int(value, api_field)
            updates.append(f"{column} = %s")
            params.append(value)
    if not updates:
        raise HTTPException(status_code=422, detail="请求体不能为空")
    params.append(photo_id)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"UPDATE photo_items SET {', '.join(updates)} WHERE id = %s", params)
            if cursor.rowcount == 0:
                _ensure_row_exists(cursor, "photo_items", photo_id, "照片不存在")
            cursor.execute("SELECT * FROM photo_items WHERE id = %s", (photo_id,))
            row = cursor.fetchone()
    return _format_photo_item(row)


@router.delete("/photos/{photo_id}")
def admin_delete_photo(photo_id: int, _: dict[str, Any] = Depends(require_admin_user)):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM photo_items WHERE id = %s", (photo_id,))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="照片不存在")
    return {"ok": True}


@router.post("/uploads")
async def admin_upload_file(
    file: UploadFile = File(...),
    target_path: str = Form(default="", alias="targetPath"),
    _: dict[str, Any] = Depends(require_admin_user),
):
    suffix = Path(file.filename or "").suffix.lower().lstrip(".")
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=422, detail="文件类型不允许")

    target_dir, relative_dir = _resolve_public_path(target_path)
    target_dir.mkdir(parents=True, exist_ok=True)
    if not target_dir.is_dir():
        raise HTTPException(status_code=422, detail="上传目标必须是目录")

    target_name = f"{secrets.token_urlsafe(18)}.{suffix}"
    target_file = target_dir / target_name
    size = 0
    with target_file.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > 50 * 1024 * 1024:
                target_file.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="文件不能超过 50MB")
            output.write(chunk)

    file_relative = target_file.relative_to(PUBLIC_DIR.resolve()).as_posix()
    return {
        "url": _file_url(file_relative),
        "filename": target_name,
        "size": size,
        "targetPath": relative_dir,
    }


@router.get("/files/tree")
def admin_file_tree(
    path: str | None = Query(default=""),
    _: dict[str, Any] = Depends(require_admin_user),
):
    target, relative = _resolve_public_path(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="目录不存在")
    if not target.is_dir():
        raise HTTPException(status_code=422, detail="只能浏览目录")

    items = [_format_file_item(item, PUBLIC_DIR.resolve()) for item in target.iterdir()]
    items.sort(key=lambda item: (item["type"] != "folder", item["name"].lower()))
    return {
        "path": relative,
        "url": _file_url(relative, is_dir=True),
        "data": items,
    }


@router.get("/db/tables")
def admin_db_tables(_: dict[str, Any] = Depends(require_admin_user)):
    return {"data": [{"name": table} for table in sorted(ALLOWED_DB_TABLES)]}


@router.get("/db/tables/{table}/schema")
def admin_db_schema(table: str, _: dict[str, Any] = Depends(require_admin_user)):
    return {"data": _visible_columns(table)}


@router.get("/db/tables/{table}/rows")
def admin_db_rows(
    table: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, alias="pageSize", ge=1, le=100),
    _: dict[str, Any] = Depends(require_admin_user),
):
    table = _ensure_table(table)
    columns = [_ensure_identifier(column["name"]) for column in _visible_columns(table)]
    if not columns:
        return {"data": [], "total": 0, "page": page, "pageSize": page_size}
    column_sql = ", ".join(f"`{column}`" for column in columns)
    offset = (page - 1) * page_size
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS total FROM `{table}`")
            total = cursor.fetchone()["total"]
            cursor.execute(
                f"SELECT {column_sql} FROM `{table}` ORDER BY id DESC LIMIT %s OFFSET %s",
                (page_size, offset),
            )
            rows = cursor.fetchall()
    return {"data": rows, "total": total, "page": page, "pageSize": page_size}


@router.post("/db/tables/{table}/rows")
def admin_db_create_row(
    table: str,
    payload: dict[str, Any],
    _: dict[str, Any] = Depends(require_admin_user),
):
    table = _ensure_table(table)
    if table == "users":
        raise HTTPException(status_code=422, detail="请通过用户管理创建用户")
    values = _filter_payload(table, payload, partial=False)
    columns = [_ensure_identifier(column) for column in values]
    placeholders = ", ".join(["%s"] * len(columns))
    column_sql = ", ".join(f"`{column}`" for column in columns)
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO `{table}` ({column_sql}) VALUES ({placeholders})",
                    [values[column] for column in columns],
                )
                row_id = cursor.lastrowid
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="数据违反唯一约束或外键约束") from exc
    return {"id": row_id}


@router.patch("/db/tables/{table}/rows/{row_id}")
def admin_db_update_row(
    table: str,
    row_id: int,
    payload: dict[str, Any],
    _: dict[str, Any] = Depends(require_admin_user),
):
    table = _ensure_table(table)
    values = _filter_payload(table, payload, partial=True)
    if not values:
        raise HTTPException(status_code=422, detail="请求体不能为空")
    columns = [_ensure_identifier(column) for column in values]
    assignments = ", ".join(f"`{column}` = %s" for column in columns)
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"UPDATE `{table}` SET {assignments} WHERE id = %s",
                    [values[column] for column in columns] + [row_id],
                )
                if cursor.rowcount == 0:
                    _ensure_row_exists(cursor, table, row_id, "记录不存在")
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="数据违反唯一约束或外键约束") from exc
    return {"ok": True}


@router.delete("/db/tables/{table}/rows/{row_id}")
def admin_db_delete_row(
    table: str,
    row_id: int,
    _: dict[str, Any] = Depends(require_admin_user),
):
    table = _ensure_table(table)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"DELETE FROM `{table}` WHERE id = %s", (row_id,))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="记录不存在")
    return {"ok": True}
