"""Admin API routes and data access helpers.

The admin module keeps privileged write operations away from the public read
routes. Every route in this file requires an authenticated admin user.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
from datetime import datetime, timezone
from sqlite3 import IntegrityError
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError
from backend.config import settings
from backend.auth import (
    create_user,
    format_user,
    get_current_user,
    hash_password,
    validate_password,
    validate_username,
)
from backend.database import get_db_connection
from backend.data_transfer import (
    TransferValidationError,
    export_transfer_document,
    import_transfer_document,
    transfer_summary,
    transfer_template,
    validate_transfer_document,
)
from backend.auth_rate_limit import (
    get_auth_security_settings,
    update_auth_security_settings,
)
from backend.avatars import delete_managed_avatar
from backend.projects import (
    format_project,
    list_project_members,
    replace_project_members,
)
from backend.project_assets import (
    IMAGE_SUFFIXES as PROJECT_IMAGE_SUFFIXES,
    ProjectAssetError,
    asset_dir_path,
    new_update_id,
    normalize_asset_dir,
    normalize_project_updates,
    normalize_relative_image_path,
    normalize_update_id,
)
from backend.resource_types import (
    ResourceTypeDefinition,
    get_resource_type,
    resource_type_options,
)
from backend.resources import (
    format_photo_activity,
    format_resource,
    yearbook_cover_url,
)

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
    "rar",
}

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")
WINDOWS_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:/")
WINDOWS_FILENAME_RESERVED_CHARS = re.compile(r'[\x00-\x1f<>:"|?*]')
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
MAX_UPLOAD_BYTES = settings.upload_max_bytes
MAX_PROJECT_PHOTO_BYTES = settings.project_photo_max_bytes


def require_admin_user(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Allow only active admin users to access admin routes."""

    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


@router.get("/auth-security-settings")
def admin_get_auth_security_settings(
    _: dict[str, Any] = Depends(require_admin_user),
):
    return get_auth_security_settings()


@router.patch("/auth-security-settings")
def admin_update_auth_security_settings(
    payload: dict[str, Any],
    admin: dict[str, Any] = Depends(require_admin_user),
):
    return update_auth_security_settings(payload, admin_user_id=admin["id"])


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


def _safe_upload_filename(filename: str | None) -> str:
    original_name = Path((filename or "").replace("\\", "/")).name
    return WINDOWS_FILENAME_RESERVED_CHARS.sub("_", original_name).strip(" .")


def _validate_public_entry_name(value: Any, field_name: str, *, trim: bool = False) -> str:
    raw_name = str(value or "")
    name = raw_name.strip() if trim else raw_name
    if not name or name in {".", ".."}:
        raise HTTPException(status_code=422, detail=f"{field_name}不能为空")
    if "/" in name or "\\" in name or WINDOWS_FILENAME_RESERVED_CHARS.search(name):
        raise HTTPException(status_code=422, detail=f"{field_name}包含不允许的字符")
    if name.endswith((" ", ".")):
        raise HTTPException(status_code=422, detail=f"{field_name}不能以空格或句点结尾")
    if len(name) > 255:
        raise HTTPException(status_code=422, detail=f"{field_name}不能超过 255 个字符")
    if name.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
        raise HTTPException(status_code=422, detail=f"{field_name}是系统保留名称")
    return name


def _folder_upload_relative_path(value: Any) -> PurePosixPath:
    raw_value = str(value or "").replace("\\", "/")
    if raw_value.startswith("/") or WINDOWS_DRIVE_PATTERN.match(raw_value):
        raise HTTPException(status_code=422, detail="文件夹内路径不合法")
    raw_parts = raw_value.split("/")
    if len(raw_parts) < 2 or any(part in {"", ".", ".."} for part in raw_parts):
        raise HTTPException(status_code=422, detail="文件夹内路径必须包含顶层文件夹且不能越级")
    parts = [
        _validate_public_entry_name(part, "文件夹内路径")
        for part in raw_parts
    ]
    relative_path = PurePosixPath(*parts)
    suffix = Path(parts[-1]).suffix.lower().lstrip(".")
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f"文件类型不允许：{relative_path.as_posix()}")
    return relative_path


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
    return format_project(row, list_project_members(project_id), admin=True)


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
    activity = format_photo_activity(row, [])
    activity["updatedAt"] = row.get("updated_at")
    return activity


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


def _normalize_project_asset_dir(value: Any, *, require_exists: bool = True) -> str:
    try:
        return normalize_asset_dir(value, require_exists=require_exists)
    except ProjectAssetError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _project_updates_json(
    value: Any,
    asset_dir: str | None,
    *,
    require_files: bool = True,
) -> str:
    if not isinstance(value, list):
        raise HTTPException(status_code=422, detail="updates 必须是数组")
    try:
        clean_updates = normalize_project_updates(
            value,
            asset_dir,
            require_files=require_files,
            allow_legacy=not bool(asset_dir),
        )
    except ProjectAssetError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return json.dumps(clean_updates, ensure_ascii=False)


def _project_update_images_form(value: str, asset_dir: str) -> list[str]:
    try:
        raw_images = json.loads(value or "[]")
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=422, detail="images 必须是 JSON 数组") from error
    if not isinstance(raw_images, list):
        raise HTTPException(status_code=422, detail="images 必须是 JSON 数组")
    images: list[str] = []
    seen: set[str] = set()
    for raw_image in raw_images:
        try:
            image = normalize_relative_image_path(
                raw_image,
                asset_dir,
                require_exists=True,
            )
        except ProjectAssetError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if image not in seen:
            images.append(image)
            seen.add(image)
    return images


def _cleanup_project_photo_files(paths: list[Path]) -> None:
    parents = {path.parent for path in paths}
    for path in paths:
        path.unlink(missing_ok=True)
    for parent in sorted(parents, key=lambda item: len(item.parts), reverse=True):
        try:
            parent.rmdir()
            parent.parent.rmdir()
        except OSError:
            pass


def _available_project_photo_path(directory: Path, filename: str) -> Path:
    safe_name = _safe_upload_filename(filename)
    suffix = Path(safe_name).suffix.lower()
    if suffix not in PROJECT_IMAGE_SUFFIXES:
        raise HTTPException(status_code=422, detail="动态照片格式不支持")
    stem = Path(safe_name).stem.strip() or "photo"
    candidate = directory / f"{stem}{suffix}"
    sequence = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{sequence}{suffix}"
        sequence += 1
    return candidate


async def _store_project_update_photos(
    uploads: list[UploadFile],
    asset_dir: str,
    update_id: str,
) -> tuple[list[str], list[Path]]:
    if not uploads:
        return [], []
    root = asset_dir_path(asset_dir, require_exists=True)
    target_dir = root / "updates" / update_id
    target_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    relative_paths: list[str] = []
    try:
        for upload in uploads:
            target = _available_project_photo_path(target_dir, upload.filename or "")
            size = 0
            with target.open("xb") as output:
                created.append(target)
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_PROJECT_PHOTO_BYTES:
                        raise HTTPException(status_code=413, detail="单张动态照片不能超过 5MB")
                    output.write(chunk)
            try:
                with Image.open(target) as image:
                    image.verify()
            except (OSError, UnidentifiedImageError) as error:
                raise HTTPException(status_code=422, detail=f"不是有效图片：{upload.filename}") from error
            relative_paths.append(target.relative_to(root).as_posix())
    except Exception:
        _cleanup_project_photo_files(created)
        raise
    return relative_paths, created


def _project_row_and_updates(project_id: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM projects WHERE id = %s LIMIT 1", (project_id,))
            row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    asset_dir = row.get("asset_dir")
    if not asset_dir:
        raise HTTPException(status_code=422, detail="请先为项目配置资源目录")
    normalized_dir = _normalize_project_asset_dir(asset_dir)
    try:
        updates = normalize_project_updates(row.get("updates"), normalized_dir, allow_legacy=True)
    except ProjectAssetError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    row["asset_dir"] = normalized_dir
    return row, updates


def _normalize_bool(value: Any) -> int:
    return 1 if value is True or str(value).lower() in {"1", "true", "yes", "on"} else 0


def _normalize_project_member_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = payload.get("members")
    if not isinstance(raw_items, list) or not raw_items:
        raise HTTPException(status_code=422, detail="项目至少需要一名成员")

    items: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    seen_person_ids: set[int] = set()
    leader_count = 0
    allowed_contact_types = {"wechat", "phone", "email", "other"}
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise HTTPException(status_code=422, detail="成员格式不正确")
        name = str(raw_item.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="成员姓名不能为空")
        name_key = name.casefold()
        if name_key in seen_names:
            raise HTTPException(status_code=422, detail=f"成员姓名不能重复：{name}")
        seen_names.add(name_key)

        role = str(raw_item.get("role") or "member").strip().lower()
        if role not in {"leader", "member"}:
            raise HTTPException(status_code=422, detail="成员身份只能是负责人或成员")
        leader_count += 1 if role == "leader" else 0

        person_id = raw_item.get("personId")
        if person_id not in {None, ""}:
            person_id = _normalize_int(person_id, "personId")
            if person_id <= 0 or person_id in seen_person_ids:
                raise HTTPException(status_code=422, detail="成员档案 ID 不合法或重复")
            seen_person_ids.add(person_id)
        else:
            person_id = None

        contact_type = str(raw_item.get("contactType") or "").strip().lower() or None
        contact_value = str(raw_item.get("contactValue") or "").strip() or None
        if contact_type and contact_type not in allowed_contact_types:
            raise HTTPException(status_code=422, detail="联系方式类型不支持")
        if bool(contact_type) != bool(contact_value):
            raise HTTPException(status_code=422, detail=f"请为 {name} 同时填写联系方式类型和联系值")

        items.append(
            {
                "personId": person_id,
                "name": name,
                "role": role,
                "contactType": contact_type,
                "contactValue": contact_value,
            }
        )

    if leader_count > 1:
        raise HTTPException(status_code=422, detail="项目最多只能有一名负责人")
    return items


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


def _require_resource_row_type(value: object) -> ResourceTypeDefinition:
    resource_type = get_resource_type(value)
    if resource_type is None:
        raise HTTPException(status_code=422, detail="不支持的资源类型")
    if resource_type.storage != "resource":
        raise HTTPException(status_code=422, detail="活动照片必须通过活动照片接口管理")
    return resource_type


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


def _download_json(document: dict[str, Any], filename: str) -> JSONResponse:
    return JSONResponse(
        content=document,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _validated_transfer(payload: Any) -> tuple[dict[str, Any], list[dict[str, str]]]:
    try:
        return validate_transfer_document(payload)
    except TransferValidationError as error:
        raise HTTPException(
            status_code=422,
            detail={"message": "JSON 导入验证失败", "errors": error.errors},
        ) from error


@router.get("/data-export")
def admin_export_all(_: dict[str, Any] = Depends(require_admin_user)):
    return _download_json(export_transfer_document(), "nethub-data-export.json")


@router.get("/data-template")
def admin_export_template(_: dict[str, Any] = Depends(require_admin_user)):
    return _download_json(transfer_template(), "nethub-data-template.json")


@router.get("/projects/{project_id}/export")
def admin_export_project(project_id: int, _: dict[str, Any] = Depends(require_admin_user)):
    try:
        document = export_transfer_document(project_id=project_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return _download_json(document, f"nethub-project-{project_id}.json")


@router.get("/resources/{resource_id}/export")
def admin_export_resource(resource_id: int, _: dict[str, Any] = Depends(require_admin_user)):
    try:
        document = export_transfer_document(resource_id=resource_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return _download_json(document, f"nethub-resource-{resource_id}.json")


@router.get("/photo-activities/{activity_id}/export")
def admin_export_photo_activity(activity_id: int, _: dict[str, Any] = Depends(require_admin_user)):
    try:
        document = export_transfer_document(activity_id=activity_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return _download_json(document, f"nethub-photo-activity-{activity_id}.json")


@router.post("/data-import/preview")
def admin_preview_data_import(
    payload: dict[str, Any],
    _: dict[str, Any] = Depends(require_admin_user),
):
    document, warnings = _validated_transfer(payload)
    return {"ok": True, "summary": transfer_summary(document), "warnings": warnings}


@router.post("/data-import")
def admin_import_data(
    payload: dict[str, Any],
    confirm_warnings: bool = Query(default=False, alias="confirmWarnings"),
    _: dict[str, Any] = Depends(require_admin_user),
):
    document, warnings = _validated_transfer(payload)
    if warnings and not confirm_warnings:
        raise HTTPException(
            status_code=409,
            detail={"message": "存在缺失或类型不符的站内路径，请确认预警后再导入", "warnings": warnings},
        )
    result = import_transfer_document(document)
    return {"ok": True, **result, "warnings": warnings}


@router.get("/resource-categories")
def admin_list_resource_categories(_: dict[str, Any] = Depends(require_admin_user)):
    return {
        "data": [
            {**resource_type, "isActive": True}
            for resource_type in resource_type_options()
        ]
    }


@router.patch("/resource-categories/reorder")
def admin_reorder_resource_categories(
    payload: dict[str, Any],
    _: dict[str, Any] = Depends(require_admin_user),
):
    raise HTTPException(status_code=409, detail="资源类型及其顺序已固定在代码中")


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
    return {"data": [format_project(row, admin=True) for row in rows]}


@router.get("/projects/{project_id}")
def admin_get_project(project_id: int, _: dict[str, Any] = Depends(require_admin_user)):
    return _fetch_project(project_id)


@router.post("/projects")
def admin_create_project(payload: dict[str, Any], _: dict[str, Any] = Depends(require_admin_user)):
    allowed_fields = {
        "name",
        "category",
        "year",
        "assetDir",
        "description",
        "casCreativity",
        "casActivity",
        "casService",
    }
    unknown = sorted(set(payload) - allowed_fields)
    if unknown:
        raise HTTPException(status_code=422, detail=f"首次创建不接受字段：{', '.join(unknown)}")
    required = ["name", "category", "year", "assetDir", "description"]
    missing = [field for field in required if payload.get(field) in {None, ""}]
    if missing:
        raise HTTPException(status_code=422, detail=f"缺少字段：{', '.join(missing)}")
    asset_dir = _normalize_project_asset_dir(payload["assetDir"])
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            _ensure_project_category(cursor, payload["category"])
            cursor.execute(
                """
                INSERT INTO projects
                  (name, leader, members, category, year, icon, asset_dir, description, media,
                   cas_creativity, cas_activity, cas_service, popularity, updates)
                VALUES (%s, %s, %s, %s, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    payload["name"],
                    "",
                    "",
                    payload["category"],
                    _normalize_int(payload["year"], "year"),
                    asset_dir,
                    payload["description"],
                    _json_list([], "media"),
                    _normalize_bool(payload.get("casCreativity")),
                    _normalize_bool(payload.get("casActivity")),
                    _normalize_bool(payload.get("casService")),
                    0,
                    _json_list([], "updates"),
                ),
            )
            project_id = cursor.lastrowid
    return _fetch_project(project_id)


@router.patch("/projects/{project_id}/members")
def admin_replace_project_members(
    project_id: int,
    payload: dict[str, Any],
    _: dict[str, Any] = Depends(require_admin_user),
):
    members = _normalize_project_member_items(payload)
    try:
        replace_project_members(project_id, members)
    except ValueError as error:
        detail = str(error)
        status_code = 404 if detail == "项目不存在" else 422
        raise HTTPException(status_code=status_code, detail=detail) from error
    return _fetch_project(project_id)


async def create_project_update_record(
    project_id: int,
    content: str,
    images: str,
    photos: list[UploadFile],
    publisher: dict[str, Any],
) -> dict[str, Any]:
    """Create one update while preserving concurrent member submissions."""

    row, _ = _project_row_and_updates(project_id)
    clean_content = content.strip()
    retained_images = _project_update_images_form(images, row["asset_dir"])
    update_id = new_update_id()
    uploaded_images, created_files = await _store_project_update_photos(
        photos, row["asset_dir"], update_id
    )
    all_images = [*retained_images, *uploaded_images]
    if not clean_content and not all_images:
        _cleanup_project_photo_files(created_files)
        raise HTTPException(status_code=422, detail="动态内容和图片不能同时为空")
    update = {
        "id": update_id,
        "content": clean_content,
        "images": all_images,
        "authorName": str(publisher["name"]).strip(),
        "authorRole": publisher["role"],
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    if publisher.get("personId"):
        update["authorPersonId"] = int(publisher["personId"])
    elif publisher.get("userId"):
        # Compatibility for administrators, who are not project member records.
        update["authorUserId"] = int(publisher["userId"])
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # The upload happens before the write lock. Reloading inside a
                # short IMMEDIATE transaction prevents two publishers from
                # replacing each other's read-modify-write result.
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute(
                    "SELECT asset_dir, updates FROM projects WHERE id = %s LIMIT 1",
                    (project_id,),
                )
                latest_row = cursor.fetchone()
                if latest_row is None:
                    raise HTTPException(status_code=404, detail="项目不存在")
                latest_asset_dir = _normalize_project_asset_dir(latest_row.get("asset_dir"))
                if latest_asset_dir != row["asset_dir"]:
                    raise HTTPException(status_code=409, detail="项目资源目录已变更，请重新发布")
                try:
                    updates = normalize_project_updates(
                        latest_row.get("updates"),
                        latest_asset_dir,
                        allow_legacy=True,
                    )
                except ProjectAssetError as error:
                    raise HTTPException(status_code=422, detail=str(error)) from error
                # The stored order is newest-first so the public feed and the
                # admin editor agree without a client-only reversal.
                updates.insert(0, update)
                cursor.execute(
                    "UPDATE projects SET updates = %s WHERE id = %s",
                    (json.dumps(updates, ensure_ascii=False), project_id),
                )
                if cursor.rowcount == 0:
                    raise HTTPException(status_code=404, detail="项目不存在")
    except Exception:
        _cleanup_project_photo_files(created_files)
        raise
    return _fetch_project(project_id)


@router.post("/projects/{project_id}/updates")
async def admin_create_project_update(
    project_id: int,
    content: str = Form(default=""),
    images: str = Form(default="[]"),
    photos: list[UploadFile] | None = File(default=None),
    author_person_id: int | None = Form(default=None, alias="authorPersonId"),
    admin: dict[str, Any] = Depends(require_admin_user),
):
    if author_person_id is None:
        raise HTTPException(status_code=422, detail="请选择项目成员作为发布者")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT pm.person_id, pm.display_name_snapshot, pm.role
                FROM project_members pm
                JOIN people p ON p.id = pm.person_id
                WHERE pm.project_id = %s
                  AND pm.person_id = %s
                  AND p.status <> 'archived'
                LIMIT 1
                """,
                (project_id, author_person_id),
            )
            member = cursor.fetchone()
    if member is None:
        raise HTTPException(status_code=422, detail="发布者必须是本项目成员")
    return await create_project_update_record(
        project_id,
        content,
        images,
        photos or [],
        {
            "personId": member["person_id"],
            "name": member["display_name_snapshot"],
            "role": member["role"],
        },
    )


@router.patch("/projects/{project_id}/updates/reorder")
def admin_reorder_project_updates(
    project_id: int,
    payload: dict[str, Any],
    _: dict[str, Any] = Depends(require_admin_user),
):
    _, updates = _project_row_and_updates(project_id)
    update_ids = payload.get("updateIds")
    if not isinstance(update_ids, list) or any(not isinstance(item, str) for item in update_ids):
        raise HTTPException(status_code=422, detail="updateIds 必须是字符串数组")
    if len(update_ids) != len(set(update_ids)):
        raise HTTPException(status_code=422, detail="updateIds 不能重复")
    current = {update["id"]: update for update in updates}
    if set(update_ids) != set(current):
        raise HTTPException(status_code=422, detail="updateIds 必须完整包含当前项目的全部动态")
    reordered = [current[update_id] for update_id in update_ids]
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE projects SET updates = %s WHERE id = %s",
                (json.dumps(reordered, ensure_ascii=False), project_id),
            )
    return _fetch_project(project_id)


@router.patch("/projects/{project_id}/updates/{update_id}")
async def admin_update_project_update(
    project_id: int,
    update_id: str,
    content: str = Form(default=""),
    images: str = Form(default="[]"),
    photos: list[UploadFile] | None = File(default=None),
    _: dict[str, Any] = Depends(require_admin_user),
):
    row, updates = _project_row_and_updates(project_id)
    target = next((item for item in updates if item["id"] == update_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="项目动态不存在")
    clean_content = content.strip()
    retained_images = _project_update_images_form(images, row["asset_dir"])
    uploaded_images, created_files = await _store_project_update_photos(
        photos or [], row["asset_dir"], update_id
    )
    all_images = [*retained_images, *uploaded_images]
    if not clean_content and not all_images:
        _cleanup_project_photo_files(created_files)
        raise HTTPException(status_code=422, detail="动态内容和图片不能同时为空")
    target["content"] = clean_content
    target["images"] = all_images
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE projects SET updates = %s WHERE id = %s",
                    (json.dumps(updates, ensure_ascii=False), project_id),
                )
                if cursor.rowcount == 0:
                    raise HTTPException(status_code=404, detail="项目不存在")
    except Exception:
        _cleanup_project_photo_files(created_files)
        raise
    return _fetch_project(project_id)


def _delete_managed_project_update_files(asset_dir: str, update_id: str) -> None:
    """Delete files uploaded into this update's managed directory only."""

    root = asset_dir_path(asset_dir, require_exists=True)
    updates_root = root / "updates"
    target = updates_root / update_id
    if target.is_symlink() or target.is_file():
        target.unlink(missing_ok=True)
    elif target.is_dir():
        shutil.rmtree(target)
    try:
        updates_root.rmdir()
    except OSError:
        pass


def delete_project_update_record(
    project_id: int,
    update_id: str,
    publisher: dict[str, Any],
) -> dict[str, Any]:
    try:
        clean_update_id = normalize_update_id(update_id, generate=False)
    except ProjectAssetError as error:
        raise HTTPException(status_code=404, detail="项目动态不存在") from error

    asset_dir = ""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                "SELECT asset_dir, updates FROM projects WHERE id = %s LIMIT 1",
                (project_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="项目不存在")
            asset_dir = _normalize_project_asset_dir(row.get("asset_dir"))
            try:
                updates = normalize_project_updates(
                    row.get("updates"),
                    asset_dir,
                    allow_legacy=True,
                )
            except ProjectAssetError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            target = next((item for item in updates if item["id"] == clean_update_id), None)
            if target is None:
                raise HTTPException(status_code=404, detail="项目动态不存在")
            can_delete_all = publisher["role"] in {"admin", "leader"}
            is_author = bool(
                publisher.get("personId")
                and target.get("authorPersonId") == int(publisher["personId"])
            ) or bool(
                not target.get("authorPersonId")
                and publisher.get("userId")
                and target.get("authorUserId") == int(publisher["userId"])
            )
            if not can_delete_all and not is_author:
                raise HTTPException(status_code=403, detail="只能删除自己发布的动态")
            retained = [item for item in updates if item["id"] != clean_update_id]
            cursor.execute(
                "UPDATE projects SET updates = %s WHERE id = %s",
                (json.dumps(retained, ensure_ascii=False), project_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="项目不存在")

    try:
        _delete_managed_project_update_files(asset_dir, clean_update_id)
    except OSError as error:
        raise HTTPException(status_code=500, detail="动态记录已删除，但本地照片清理失败") from error
    return _fetch_project(project_id)


@router.delete("/projects/{project_id}/updates/{update_id}")
def admin_delete_project_update(
    project_id: int,
    update_id: str,
    admin: dict[str, Any] = Depends(require_admin_user),
):
    return delete_project_update_record(
        project_id,
        update_id,
        {
            "userId": admin["id"],
            "name": admin.get("displayName") or admin.get("username") or "管理员",
            "role": "admin",
        },
    )


@router.patch("/projects/{project_id}")
def admin_update_project(
    project_id: int,
    payload: dict[str, Any],
    _: dict[str, Any] = Depends(require_admin_user),
):
    field_map = {
        "name": "name",
        "category": "category",
        "year": "year",
        "assetDir": "asset_dir",
        "description": "description",
        "casCreativity": "cas_creativity",
        "casActivity": "cas_activity",
        "casService": "cas_service",
        "updates": "updates",
    }
    unknown = sorted(set(payload) - set(field_map))
    if unknown:
        raise HTTPException(status_code=422, detail=f"字段不允许编辑：{', '.join(unknown)}")
    for required_text_field in {"name", "category", "description"}:
        if required_text_field not in payload:
            continue
        clean_value = str(payload[required_text_field] or "").strip()
        if not clean_value:
            raise HTTPException(status_code=422, detail=f"{required_text_field} 不能为空")
        payload[required_text_field] = clean_value
    updates = []
    params: list[Any] = []
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM projects WHERE id = %s LIMIT 1", (project_id,))
            current = cursor.fetchone()
            if current is None:
                raise HTTPException(status_code=404, detail="项目不存在")
            next_asset_dir = current.get("asset_dir")
            if "assetDir" in payload:
                next_asset_dir = _normalize_project_asset_dir(payload["assetDir"])
                payload["assetDir"] = next_asset_dir
                if "updates" not in payload:
                    # Changing the root must not silently break stored relative paths.
                    _project_updates_json(
                        normalize_project_updates(
                            current.get("updates"),
                            current.get("asset_dir"),
                            allow_legacy=True,
                        ),
                        next_asset_dir,
                    )
            if "category" in payload:
                _ensure_project_category(cursor, payload["category"])
            for api_field, column in field_map.items():
                if api_field not in payload:
                    continue
                value = payload[api_field]
                if api_field == "year":
                    value = _normalize_int(value, api_field)
                if api_field in {"casCreativity", "casActivity", "casService"}:
                    value = _normalize_bool(value)
                if api_field == "updates":
                    value = _project_updates_json(value, next_asset_dir)
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
    where_parts = ["deleted_at IS NULL"]
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
    allowed = {"role", "isActive", "displayName"}
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
    if "displayName" in payload:
        display_name = str(payload.get("displayName") or "").strip() or None
        if display_name and len(display_name) > 80:
            raise HTTPException(status_code=422, detail="姓名长度不能超过 80 位")
        updates.append("display_name = %s")
        params.append(display_name)
    if not updates:
        raise HTTPException(status_code=422, detail="请求体不能为空")

    params.append(user_id)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE id = %s AND deleted_at IS NULL",
                params,
            )
            if cursor.rowcount == 0:
                cursor.execute("SELECT id FROM users WHERE id = %s AND deleted_at IS NULL", (user_id,))
                if cursor.fetchone() is None:
                    raise HTTPException(status_code=404, detail="用户不存在")
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            row = cursor.fetchone()
    return format_user(row)


@router.delete("/users/{user_id}")
def admin_delete_user(
    user_id: int,
    admin: dict[str, Any] = Depends(require_admin_user),
):
    if user_id == admin["id"]:
        raise HTTPException(status_code=409, detail="不能删除当前登录的管理员账号")

    old_avatar_url: str | None = None
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE id = %s AND deleted_at IS NULL LIMIT 1", (user_id,))
            target = cursor.fetchone()
            if target is None:
                raise HTTPException(status_code=404, detail="用户不存在")
            if target["role"] == "admin" and target["is_active"]:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM users
                    WHERE role = 'admin' AND is_active = 1 AND deleted_at IS NULL
                    """
                )
                if cursor.fetchone()["total"] <= 1:
                    raise HTTPException(status_code=409, detail="不能删除最后一个启用的管理员")

            old_avatar_url = target.get("avatar_url")
            cursor.execute(
                "UPDATE people SET user_id = NULL, status = 'provisional' WHERE user_id = %s",
                (user_id,),
            )
            cursor.execute(
                "DELETE FROM person_claims WHERE user_id = %s AND status = 'pending'",
                (user_id,),
            )
            cursor.execute(
                "DELETE FROM user_follows WHERE follower_id = %s OR following_id = %s",
                (user_id, user_id),
            )
            cursor.execute(
                "DELETE FROM user_blocks WHERE blocker_id = %s OR blocked_id = %s",
                (user_id, user_id),
            )
            tombstone_username = f"deleted_{user_id}_{secrets.token_hex(4)}"
            cursor.execute(
                """
                UPDATE users
                SET username = %s,
                    password_hash = %s,
                    display_name = NULL,
                    avatar_url = NULL,
                    bio = '',
                    role = 'user',
                    is_active = 0,
                    campus_verified = 0,
                    messaging_permission = 'nobody',
                    last_seen_at = NULL,
                    deleted_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (tombstone_username, f"deleted${secrets.token_hex(32)}", user_id),
            )

    delete_managed_avatar(old_avatar_url)
    return {"ok": True}


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
        _require_resource_row_type(category)
        where_parts.append("category = %s")
        params.append(category)
    if year:
        where_parts.append("year = %s")
        params.append(year)
    if search:
        where_parts.append("(title LIKE %s OR description LIKE %s OR label LIKE %s)")
        keyword = f"%{search}%"
        params.extend([keyword, keyword, keyword])
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT * FROM resources {where_sql} ORDER BY id DESC", params)
            rows = cursor.fetchall()
    return {"data": [format_resource(row) for row in rows]}


@router.post("/resources")
def admin_create_resource(payload: dict[str, Any], _: dict[str, Any] = Depends(require_admin_user)):
    resource_type = _require_resource_row_type(payload.get("category"))
    required = ["title", "year", "category", "resourceUrl"]
    if resource_type.value not in {"teacher", "yearbook"}:
        required.append("image")
    missing = [field for field in required if payload.get(field) in {None, ""}]
    if missing:
        raise HTTPException(status_code=422, detail=f"缺少字段：{', '.join(missing)}")
    image = payload.get("image")
    if resource_type.value == "yearbook":
        if not yearbook_cover_url(payload.get("resourceUrl")):
            raise HTTPException(status_code=422, detail="Yearbook 目录中必须至少有一张图片作为封面和第一页")
        image = str(image or "").strip()
    elif resource_type.value == "teacher":
        image = str(image or "").strip()
        payload["downloads"] = 0
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO resources
                  (title, description, year, category, label, hot, downloads, image, resource_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    payload["title"],
                    payload.get("description") or "",
                    _normalize_int(payload["year"], "year"),
                    resource_type.value,
                    resource_type.label,
                    0,
                    _normalize_int(payload.get("downloads", 0), "downloads"),
                    image,
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
        "downloads": "downloads",
        "image": "image",
        "resourceUrl": "resource_url",
    }
    unknown = sorted(set(payload) - set(field_map))
    if unknown:
        raise HTTPException(status_code=422, detail=f"字段不允许编辑：{', '.join(unknown)}")
    if not payload:
        raise HTTPException(status_code=422, detail="请求体不能为空")

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT title, description, year, category, image, resource_url
                FROM resources
                WHERE id = %s
                LIMIT 1
                """,
                (resource_id,),
            )
            current = cursor.fetchone()
    if current is None:
        raise HTTPException(status_code=404, detail="资源不存在")

    next_resource_url = payload.get("resourceUrl", current["resource_url"])
    resource_type = _require_resource_row_type(payload.get("category", current["category"]))
    payload["category"] = resource_type.value
    payload["label"] = resource_type.label
    if resource_type.value == "yearbook":
        if not yearbook_cover_url(next_resource_url):
            raise HTTPException(status_code=422, detail="Yearbook 目录中必须至少有一张图片作为封面和第一页")
        payload["image"] = str(payload.get("image", current["image"]) or "").strip()
    elif resource_type.value == "teacher":
        required_values = {
            "title": payload.get("title", current["title"]),
            "year": payload.get("year", current["year"]),
            "resourceUrl": next_resource_url,
        }
        missing = [field for field, value in required_values.items() if value in {None, ""}]
        if missing:
            raise HTTPException(status_code=422, detail=f"缺少字段：{', '.join(missing)}")
        payload["image"] = str(payload.get("image", current["image"]) or "").strip()
    elif not payload.get("image", current["image"]):
        raise HTTPException(status_code=422, detail="缺少字段：image")
    updates = []
    params: list[Any] = []
    for api_field, column in field_map.items():
        if api_field in payload:
            value = payload[api_field]
            if api_field in {"year", "downloads"}:
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
                GROUP BY pa.id, pa.activity, pa.description, pa.year, pa.hot, pa.downloads, pa.sort_order, pa.photo_dir, pa.cover_image, pa.created_at, pa.updated_at
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
    required = ["activity", "year"]
    missing = [field for field in required if payload.get(field) in {None, ""}]
    if missing:
        raise HTTPException(status_code=422, detail=f"缺少字段：{', '.join(missing)}")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO photo_activities
                  (activity, description, year, hot, downloads, sort_order, photo_dir, cover_image)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    payload["activity"],
                    payload.get("description") or "",
                    _normalize_int(payload["year"], "year"),
                    0,
                    _normalize_int(payload.get("downloads", 0), "downloads"),
                    _normalize_int(payload.get("sortOrder", _next_activity_sort_order(cursor)), "sortOrder"),
                    _normalize_public_url(payload.get("photoDir")),
                    str(payload.get("coverImage") or "").strip() or None,
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
        "downloads": "downloads",
        "sortOrder": "sort_order",
        "photoDir": "photo_dir",
        "coverImage": "cover_image",
    }
    unknown = sorted(set(payload) - set(field_map))
    if unknown:
        raise HTTPException(status_code=422, detail=f"字段不允许编辑：{', '.join(unknown)}")
    updates = []
    params: list[Any] = []
    for api_field, column in field_map.items():
        if api_field in payload:
            value = payload[api_field]
            if api_field in {"year", "downloads", "sortOrder"}:
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
                GROUP BY pa.id, pa.activity, pa.description, pa.year, pa.hot, pa.downloads, pa.sort_order, pa.photo_dir, pa.cover_image, pa.created_at, pa.updated_at
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

    original_name = _safe_upload_filename(file.filename)
    target_name = original_name if suffix == "rar" and original_name else f"{secrets.token_urlsafe(18)}.{suffix}"
    target_file = target_dir / target_name
    size = 0
    with target_file.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
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


@router.post("/files/folders")
def admin_create_folder(
    payload: dict[str, Any],
    _: dict[str, Any] = Depends(require_admin_user),
):
    parent_dir, _ = _resolve_public_path(payload.get("parentPath"))
    if not parent_dir.exists():
        raise HTTPException(status_code=404, detail="目标目录不存在")
    if not parent_dir.is_dir():
        raise HTTPException(status_code=422, detail="目标路径必须是目录")

    folder_name = _validate_public_entry_name(payload.get("name"), "文件夹名称", trim=True)
    target_dir = parent_dir / folder_name
    if target_dir.exists():
        raise HTTPException(status_code=409, detail="同名文件或文件夹已存在")
    try:
        target_dir.mkdir()
    except FileExistsError as error:
        raise HTTPException(status_code=409, detail="同名文件或文件夹已存在") from error
    except OSError as error:
        raise HTTPException(status_code=422, detail="无法创建文件夹") from error
    return {"ok": True, "data": _format_file_item(target_dir, PUBLIC_DIR.resolve())}


@router.post("/files/folder-upload")
async def admin_upload_folder(
    files: list[UploadFile] = File(...),
    relative_paths: list[str] = Form(..., alias="relativePaths"),
    target_path: str = Form(default="", alias="targetPath"),
    _: dict[str, Any] = Depends(require_admin_user),
):
    if not files:
        raise HTTPException(status_code=422, detail="所选文件夹中没有可上传文件")
    if len(files) != len(relative_paths):
        raise HTTPException(status_code=422, detail="文件与相对路径数量不一致")

    normalized_paths = [_folder_upload_relative_path(path) for path in relative_paths]
    path_keys = [path.as_posix().casefold() for path in normalized_paths]
    if len(path_keys) != len(set(path_keys)):
        raise HTTPException(status_code=422, detail="文件夹中包含重名文件")
    file_path_keys = set(path_keys)
    for relative_path in normalized_paths:
        parts = relative_path.parts
        for depth in range(2, len(parts)):
            parent_key = "/".join(parts[:depth]).casefold()
            if parent_key in file_path_keys:
                raise HTTPException(status_code=422, detail="文件夹内文件和子目录名称冲突")

    root_names = {path.parts[0] for path in normalized_paths}
    if len(root_names) != 1:
        raise HTTPException(status_code=422, detail="一次只能上传一个文件夹")
    root_name = root_names.pop()

    target_dir, relative_dir = _resolve_public_path(target_path)
    if not target_dir.exists():
        raise HTTPException(status_code=404, detail="上传目标目录不存在")
    if not target_dir.is_dir():
        raise HTTPException(status_code=422, detail="上传目标必须是目录")

    uploaded_root = target_dir / root_name
    if uploaded_root.exists():
        raise HTTPException(status_code=409, detail=f"同名文件夹已存在：{root_name}")

    total_size = 0
    created_root = False
    try:
        uploaded_root.mkdir()
        created_root = True
        for upload, relative_path in zip(files, normalized_paths):
            target_file = target_dir.joinpath(*relative_path.parts)
            target_file.parent.mkdir(parents=True, exist_ok=True)
            file_size = 0
            with target_file.open("xb") as output:
                while chunk := await upload.read(1024 * 1024):
                    file_size += len(chunk)
                    if file_size > MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"单个文件不能超过 50MB：{relative_path.as_posix()}",
                        )
                    output.write(chunk)
            total_size += file_size
    except FileExistsError as error:
        if created_root:
            shutil.rmtree(uploaded_root, ignore_errors=True)
        raise HTTPException(status_code=409, detail="文件夹内包含重名路径") from error
    except Exception:
        if created_root:
            shutil.rmtree(uploaded_root, ignore_errors=True)
        raise

    uploaded_relative = uploaded_root.relative_to(PUBLIC_DIR.resolve()).as_posix()
    return {
        "ok": True,
        "folderPath": uploaded_relative,
        "folderUrl": _file_url(uploaded_relative, is_dir=True),
        "fileCount": len(files),
        "size": total_size,
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
