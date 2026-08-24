"""Versioned JSON import/export for administrator-managed content.

The transfer format is intentionally portable: database IDs, account bindings and
timestamps are not transferred. Every import creates fresh content records while
preserving business fields, counters, ordering and public/external asset paths.
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from backend.config import PROJECT_ROOT
from backend.database import get_db_connection
from backend.project_assets import (
    ProjectAssetError,
    infer_asset_dir,
    new_update_id,
    normalize_asset_dir,
    normalize_project_updates,
    normalize_relative_image_path,
)
from backend.resource_types import get_resource_type


TRANSFER_FORMAT = "nethub-campus-wiki-data"
TRANSFER_VERSION = 2
MAX_IMPORT_BYTES = 5 * 1024 * 1024
PUBLIC_DIR = PROJECT_ROOT / "public"
WINDOWS_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:[/\\]")
URL_SCHEME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}


class TransferValidationError(ValueError):
    """Raised with field-addressed errors for an invalid transfer document."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        super().__init__("JSON 导入验证失败")
        self.errors = errors


def _issue(path: str, message: str) -> dict[str, str]:
    return {"path": path, "message": message}


def _unknown_fields(value: dict[str, Any], allowed: set[str], path: str, errors: list[dict[str, str]]) -> None:
    for field in sorted(set(value) - allowed):
        errors.append(_issue(f"{path}.{field}" if path else field, "不支持的字段"))


def _object(value: Any, path: str, errors: list[dict[str, str]]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    errors.append(_issue(path, "必须是对象"))
    return {}


def _array(value: Any, path: str, errors: list[dict[str, str]]) -> list[Any]:
    if isinstance(value, list):
        return value
    errors.append(_issue(path, "必须是数组"))
    return []


def _text(
    value: Any,
    path: str,
    errors: list[dict[str, str]],
    *,
    required: bool = False,
    default: str = "",
) -> str:
    if value is None:
        text = default
    elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
        text = str(value).strip()
    else:
        errors.append(_issue(path, "必须是文本"))
        return default
    if required and not text:
        errors.append(_issue(path, "不能为空"))
    return text


def _integer(
    value: Any,
    path: str,
    errors: list[dict[str, str]],
    *,
    default: int = 0,
    minimum: int | None = None,
) -> int:
    if value is None:
        result = default
    elif isinstance(value, bool):
        errors.append(_issue(path, "必须是整数"))
        return default
    else:
        try:
            result = int(value)
        except (TypeError, ValueError):
            errors.append(_issue(path, "必须是整数"))
            return default
    if minimum is not None and result < minimum:
        errors.append(_issue(path, f"不能小于 {minimum}"))
    return result


def _boolean(value: Any, path: str, errors: list[dict[str, str]], *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    errors.append(_issue(path, "必须是布尔值"))
    return default


def _normalize_asset_url(
    value: Any,
    path: str,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
    *,
    required: bool = False,
    expected: str = "file",
    allow_external: bool = True,
) -> str | None:
    raw = _text(value, path, errors, required=required)
    if not raw:
        return None
    if raw.startswith(("https://", "http://")):
        if not allow_external:
            errors.append(_issue(path, "该字段必须使用 public 目录内的路径"))
            return None
        return raw
    if URL_SCHEME_PATTERN.match(raw) or WINDOWS_DRIVE_PATTERN.match(raw):
        errors.append(_issue(path, "只允许 http(s) URL 或 public 目录内的路径"))
        return None

    clean = raw.replace("\\", "/")
    relative = clean.strip("/")
    parts = Path(relative).parts
    if not relative or ".." in parts:
        errors.append(_issue(path, "public 路径不合法"))
        return None
    target = (PUBLIC_DIR / relative).resolve()
    public_root = PUBLIC_DIR.resolve()
    if public_root not in target.parents:
        errors.append(_issue(path, "路径必须位于 public 目录内"))
        return None

    # 普通资源允许引用文件或目录；如果目标尚不存在，则用原始尾斜杠保留调用方意图。
    is_dir = expected == "directory" or (
        expected == "any" and (clean.endswith("/") or (target.exists() and target.is_dir()))
    )
    normalized = f"/{relative.rstrip('/')}" + ("/" if is_dir else "")
    if not target.exists():
        warnings.append(_issue(path, f"站内路径不存在：{normalized}"))
    elif expected == "file" and not target.is_file():
        warnings.append(_issue(path, f"预期为文件，但当前是目录：{normalized}"))
    elif expected == "directory" and not target.is_dir():
        warnings.append(_issue(path, f"预期为目录，但当前是文件：{normalized}"))
    return normalized


def _normalize_member(value: Any, path: str, errors: list[dict[str, str]]) -> dict[str, Any]:
    item = _object(value, path, errors)
    _unknown_fields(item, {"name", "role", "contactType", "contactValue"}, path, errors)
    name = _text(item.get("name"), f"{path}.name", errors, required=True)
    role = _text(item.get("role", "member"), f"{path}.role", errors) or "member"
    if role not in {"leader", "member"}:
        errors.append(_issue(f"{path}.role", "只能是 leader 或 member"))
        role = "member"
    contact_type = _text(item.get("contactType"), f"{path}.contactType", errors) or None
    contact_value = _text(item.get("contactValue"), f"{path}.contactValue", errors) or None
    if contact_type not in {None, "wechat", "phone", "email", "other"}:
        errors.append(_issue(f"{path}.contactType", "不支持的联系方式类型"))
    if bool(contact_type) != bool(contact_value):
        errors.append(_issue(path, "联系方式类型和联系值必须同时填写或同时留空"))
    return {
        "name": name,
        "role": role,
        "contactType": contact_type,
        "contactValue": contact_value,
    }


def _normalize_update(
    value: Any,
    path: str,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
    asset_dir: str | None,
) -> dict[str, Any]:
    item = _object(value, path, errors)
    _unknown_fields(item, {"id", "content", "images"}, path, errors)
    update_id = _text(item.get("id"), f"{path}.id", errors) or new_update_id()
    if not re.fullmatch(r"[a-f0-9]{32}", update_id):
        errors.append(_issue(f"{path}.id", "必须是 32 位小写十六进制字符串"))
        update_id = new_update_id()
    content = _text(item.get("content"), f"{path}.content", errors)
    images = []
    seen: set[str] = set()
    for index, raw_image in enumerate(_array(item.get("images", []), f"{path}.images", errors)):
        if not asset_dir:
            errors.append(_issue(f"{path}.images[{index}]", "项目缺少 assetDir"))
            continue
        try:
            image = normalize_relative_image_path(raw_image, asset_dir)
        except ProjectAssetError as error:
            errors.append(_issue(f"{path}.images[{index}]", str(error)))
            continue
        target = PUBLIC_DIR / asset_dir.strip("/") / Path(*PurePosixPath(image).parts)
        if not target.is_file():
            warnings.append(_issue(f"{path}.images[{index}]", f"动态图片不存在：{image}"))
        if image and image not in seen:
            images.append(image)
            seen.add(image)
    if not content and not images:
        errors.append(_issue(path, "动态内容和图片不能同时为空"))
    return {"id": update_id, "content": content, "images": images}


def _normalize_project(
    value: Any,
    path: str,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
    version: int,
) -> dict[str, Any]:
    item = _object(value, path, errors)
    allowed_fields = {
        "name", "category", "year", "assetDir", "description", "cas",
        "popularity", "members", "updates",
    }
    if version == 1:
        allowed_fields.add("icon")
    _unknown_fields(
        item,
        allowed_fields,
        path,
        errors,
    )
    cas = _object(item.get("cas", {}), f"{path}.cas", errors)
    _unknown_fields(cas, {"creativity", "activity", "service"}, f"{path}.cas", errors)
    members = [
        _normalize_member(member, f"{path}.members[{index}]", errors)
        for index, member in enumerate(_array(item.get("members", []), f"{path}.members", errors))
    ]
    name_keys = [member["name"].casefold() for member in members if member["name"]]
    if len(name_keys) != len(set(name_keys)):
        errors.append(_issue(f"{path}.members", "成员姓名不能重复"))
    if sum(member["role"] == "leader" for member in members) > 1:
        errors.append(_issue(f"{path}.members", "最多只能有一名负责人"))
    asset_dir: str | None = None
    if version == 1:
        asset_dir = infer_asset_dir(item.get("icon"), item.get("updates"))
        if asset_dir:
            warnings.append(_issue(f"{path}.assetDir", f"已从 v1 路径推断为 {asset_dir}"))
        else:
            errors.append(_issue(f"{path}.assetDir", "无法从 v1 的 icon 或动态图片推断 CAS 项目目录"))
    else:
        raw_asset_dir = _text(item.get("assetDir"), f"{path}.assetDir", errors, required=True)
        if raw_asset_dir:
            try:
                asset_dir = normalize_asset_dir(raw_asset_dir)
            except ProjectAssetError as error:
                errors.append(_issue(f"{path}.assetDir", str(error)))
            else:
                target = PUBLIC_DIR / asset_dir.strip("/")
                if not target.is_dir():
                    warnings.append(_issue(f"{path}.assetDir", f"站内目录不存在：{asset_dir}"))
    updates = [
        _normalize_update(update, f"{path}.updates[{index}]", errors, warnings, asset_dir)
        for index, update in enumerate(_array(item.get("updates", []), f"{path}.updates", errors))
    ]
    return {
        "name": _text(item.get("name"), f"{path}.name", errors, required=True),
        "category": _text(item.get("category"), f"{path}.category", errors, required=True),
        "year": _integer(item.get("year"), f"{path}.year", errors, minimum=1900),
        "assetDir": asset_dir,
        "description": _text(item.get("description"), f"{path}.description", errors, required=True),
        "cas": {
            "creativity": _boolean(cas.get("creativity"), f"{path}.cas.creativity", errors),
            "activity": _boolean(cas.get("activity"), f"{path}.cas.activity", errors),
            "service": _boolean(cas.get("service"), f"{path}.cas.service", errors),
        },
        "popularity": _integer(item.get("popularity"), f"{path}.popularity", errors, minimum=0),
        "members": members,
        "updates": updates,
    }


def _normalize_resource(
    value: Any,
    path: str,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> dict[str, Any]:
    item = _object(value, path, errors)
    _unknown_fields(
        item,
        {"title", "description", "year", "category", "label", "hot", "downloads", "image", "resourceUrl"},
        path,
        errors,
    )
    category = _text(item.get("category"), f"{path}.category", errors, required=True)
    resource_type = get_resource_type(category)
    if resource_type is None or resource_type.storage != "resource":
        errors.append(_issue(f"{path}.category", "只能是 yearbook、teacher 或 other"))
        category = "other"
        resource_type = get_resource_type(category)
    expected_resource = "directory" if category == "yearbook" else ("file" if category == "teacher" else "any")
    image_required = category == "other"
    return {
        "title": _text(item.get("title"), f"{path}.title", errors, required=True),
        "description": _text(item.get("description"), f"{path}.description", errors, required=category == "teacher"),
        "year": _integer(item.get("year"), f"{path}.year", errors, minimum=1900),
        "category": category,
        "label": resource_type.label,
        "hot": _integer(item.get("hot"), f"{path}.hot", errors, minimum=0),
        "downloads": _integer(item.get("downloads"), f"{path}.downloads", errors, minimum=0),
        "image": _normalize_asset_url(
            item.get("image"),
            f"{path}.image",
            errors,
            warnings,
            required=image_required,
        ) or "",
        "resourceUrl": _normalize_asset_url(
            item.get("resourceUrl"),
            f"{path}.resourceUrl",
            errors,
            warnings,
            required=True,
            expected=expected_resource,
            allow_external=category != "yearbook",
        ) or "",
    }


def _normalize_photo(
    value: Any,
    path: str,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> dict[str, Any]:
    item = _object(value, path, errors)
    _unknown_fields(item, {"title", "src", "sortOrder"}, path, errors)
    return {
        "title": _text(item.get("title"), f"{path}.title", errors, required=True),
        "src": _normalize_asset_url(
            item.get("src"), f"{path}.src", errors, warnings, required=True
        ) or "",
        "sortOrder": _integer(item.get("sortOrder"), f"{path}.sortOrder", errors, minimum=0),
    }


def _normalize_photo_activity(
    value: Any,
    path: str,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> dict[str, Any]:
    item = _object(value, path, errors)
    _unknown_fields(
        item,
        {"activity", "description", "year", "hot", "downloads", "sortOrder", "photoDir", "photos"},
        path,
        errors,
    )
    photos = [
        _normalize_photo(photo, f"{path}.photos[{index}]", errors, warnings)
        for index, photo in enumerate(_array(item.get("photos", []), f"{path}.photos", errors))
    ]
    return {
        "activity": _text(item.get("activity"), f"{path}.activity", errors, required=True),
        "description": _text(item.get("description"), f"{path}.description", errors, required=True),
        "year": _integer(item.get("year"), f"{path}.year", errors, minimum=1900),
        "hot": _integer(item.get("hot"), f"{path}.hot", errors, minimum=0),
        "downloads": _integer(item.get("downloads"), f"{path}.downloads", errors, minimum=0),
        "sortOrder": _integer(item.get("sortOrder"), f"{path}.sortOrder", errors, minimum=0),
        "photoDir": _normalize_asset_url(
            item.get("photoDir"),
            f"{path}.photoDir",
            errors,
            warnings,
            expected="directory",
            allow_external=False,
        ),
        "photos": photos,
    }


def transfer_summary(document: dict[str, Any]) -> dict[str, int]:
    projects = document["projects"]
    resources = document["resources"]
    activities = document["photoActivities"]
    return {
        "projects": len(projects),
        "members": sum(len(project["members"]) for project in projects),
        "updates": sum(len(project["updates"]) for project in projects),
        "resources": len(resources),
        "photoActivities": len(activities),
        "photos": sum(len(activity["photos"]) for activity in activities),
    }


def validate_transfer_document(payload: Any) -> tuple[dict[str, Any], list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    document = _object(payload, "document", errors)
    _unknown_fields(
        document,
        {"format", "version", "exportedAt", "projects", "resources", "photoActivities"},
        "",
        errors,
    )
    if document.get("format") != TRANSFER_FORMAT:
        errors.append(_issue("format", f"必须是 {TRANSFER_FORMAT}"))
    version = document.get("version")
    if version not in {1, TRANSFER_VERSION}:
        errors.append(_issue("version", f"当前支持版本 1 和 {TRANSFER_VERSION}"))
        version = TRANSFER_VERSION

    encoded_size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    if encoded_size > MAX_IMPORT_BYTES:
        errors.append(_issue("document", "JSON 文件不能超过 5 MB；请只保存路径，不要嵌入 Base64 文件"))

    projects = [
        _normalize_project(project, f"projects[{index}]", errors, warnings, int(version))
        for index, project in enumerate(_array(document.get("projects", []), "projects", errors))
    ]
    resources = [
        _normalize_resource(resource, f"resources[{index}]", errors, warnings)
        for index, resource in enumerate(_array(document.get("resources", []), "resources", errors))
    ]
    photo_activities = [
        _normalize_photo_activity(activity, f"photoActivities[{index}]", errors, warnings)
        for index, activity in enumerate(_array(document.get("photoActivities", []), "photoActivities", errors))
    ]
    if not projects and not resources and not photo_activities:
        errors.append(_issue("document", "至少需要包含一个项目或资源"))
    if errors:
        raise TransferValidationError(errors)
    return {
        "format": TRANSFER_FORMAT,
        "version": TRANSFER_VERSION,
        "projects": projects,
        "resources": resources,
        "photoActivities": photo_activities,
    }, warnings


def _parse_updates(value: Any, asset_dir: str | None) -> list[dict[str, Any]]:
    try:
        return normalize_project_updates(value, asset_dir, allow_legacy=True)
    except ProjectAssetError:
        return []


def _new_document() -> dict[str, Any]:
    return {
        "format": TRANSFER_FORMAT,
        "version": TRANSFER_VERSION,
        "exportedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "projects": [],
        "resources": [],
        "photoActivities": [],
    }


def export_transfer_document(
    *,
    project_id: int | None = None,
    resource_id: int | None = None,
    activity_id: int | None = None,
) -> dict[str, Any]:
    """Export all content, or exactly one requested entity, in the canonical envelope."""

    filters = [project_id is not None, resource_id is not None, activity_id is not None]
    export_all = not any(filters)
    if sum(filters) > 1:
        raise ValueError("一次只能导出一个指定实体")
    document = _new_document()
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            project_params: list[Any] = []
            project_where = ""
            if project_id is not None:
                project_where = "WHERE id = %s"
                project_params.append(project_id)
            if export_all or project_id is not None:
                cursor.execute(f"SELECT * FROM projects {project_where} ORDER BY id ASC", project_params)
                project_rows = cursor.fetchall()
                if project_id is not None and not project_rows:
                    raise LookupError("项目不存在")
                for row in project_rows:
                    cursor.execute(
                        """
                        SELECT pm.display_name_snapshot, pm.role, pm.contact_type, pm.contact_value
                        FROM project_members pm
                        WHERE pm.project_id = %s
                        ORDER BY CASE pm.role WHEN 'leader' THEN 0 ELSE 1 END,
                                 pm.sort_order ASC, pm.person_id ASC
                        """,
                        (row["id"],),
                    )
                    members = [
                        {
                            "name": member["display_name_snapshot"],
                            "role": member["role"],
                            "contactType": member.get("contact_type"),
                            "contactValue": member.get("contact_value"),
                        }
                        for member in cursor.fetchall()
                    ]
                    document["projects"].append(
                        {
                            "name": row["name"],
                            "category": row["category"],
                            "year": row["year"],
                            "assetDir": row.get("asset_dir"),
                            "description": row["description"],
                            "cas": {
                                "creativity": bool(row["cas_creativity"]),
                                "activity": bool(row["cas_activity"]),
                                "service": bool(row["cas_service"]),
                            },
                            "popularity": row["popularity"],
                            "members": members,
                            "updates": _parse_updates(row.get("updates"), row.get("asset_dir")),
                        }
                    )

            resource_params: list[Any] = []
            resource_where = ""
            if resource_id is not None:
                resource_where = "WHERE id = %s"
                resource_params.append(resource_id)
            if export_all or resource_id is not None:
                cursor.execute(f"SELECT * FROM resources {resource_where} ORDER BY id ASC", resource_params)
                resource_rows = cursor.fetchall()
                if resource_id is not None and not resource_rows:
                    raise LookupError("资源不存在")
                document["resources"] = [
                    {
                        "title": row["title"],
                        "description": row.get("description") or "",
                        "year": row["year"],
                        "category": row["category"],
                        "label": row["label"],
                        "hot": row["hot"],
                        "downloads": row["downloads"],
                        "image": row["image"],
                        "resourceUrl": row["resource_url"],
                    }
                    for row in resource_rows
                ]

            activity_params: list[Any] = []
            activity_where = ""
            if activity_id is not None:
                activity_where = "WHERE id = %s"
                activity_params.append(activity_id)
            if export_all or activity_id is not None:
                cursor.execute(f"SELECT * FROM photo_activities {activity_where} ORDER BY id ASC", activity_params)
                activity_rows = cursor.fetchall()
                if activity_id is not None and not activity_rows:
                    raise LookupError("活动不存在")
                for row in activity_rows:
                    cursor.execute(
                        """
                        SELECT title, image_url, sort_order
                        FROM photo_items
                        WHERE activity_id = %s
                        ORDER BY sort_order ASC, id ASC
                        """,
                        (row["id"],),
                    )
                    document["photoActivities"].append(
                        {
                            "activity": row["activity"],
                            "description": row["description"],
                            "year": row["year"],
                            "hot": row["hot"],
                            "downloads": row.get("downloads", 0),
                            "sortOrder": row["sort_order"],
                            "photoDir": row.get("photo_dir"),
                            "photos": [
                                {
                                    "title": photo["title"],
                                    "src": photo["image_url"],
                                    "sortOrder": photo["sort_order"],
                                }
                                for photo in cursor.fetchall()
                            ],
                        }
                    )
    return document


def import_transfer_document(document: dict[str, Any]) -> dict[str, Any]:
    """Create every normalized item in one database transaction."""

    created: dict[str, list[dict[str, Any]]] = {
        "projects": [],
        "resources": [],
        "photoActivities": [],
    }
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            for project in document["projects"]:
                cursor.execute("SELECT id FROM project_categories WHERE name = %s LIMIT 1", (project["category"],))
                if cursor.fetchone() is None:
                    cursor.execute("SELECT COALESCE(MAX(sort_order), 0) + 10 AS next_order FROM project_categories")
                    next_order = cursor.fetchone()["next_order"]
                    cursor.execute(
                        "INSERT INTO project_categories (name, sort_order, is_active) VALUES (%s, %s, 1)",
                        (project["category"], next_order),
                    )
                leader_name = next(
                    (member["name"] for member in project["members"] if member["role"] == "leader"),
                    "",
                )
                member_summary = ", ".join(member["name"] for member in project["members"])
                cursor.execute(
                    """
                    INSERT INTO projects
                      (name, leader, members, category, year, icon, asset_dir, description, media,
                       cas_creativity, cas_activity, cas_service, popularity, updates)
                    VALUES (%s, %s, %s, %s, %s, NULL, %s, %s, '[]', %s, %s, %s, %s, %s)
                    """,
                    (
                        project["name"],
                        leader_name,
                        member_summary,
                        project["category"],
                        project["year"],
                        project["assetDir"],
                        project["description"],
                        1 if project["cas"]["creativity"] else 0,
                        1 if project["cas"]["activity"] else 0,
                        1 if project["cas"]["service"] else 0,
                        project["popularity"],
                        json.dumps(project["updates"], ensure_ascii=False),
                    ),
                )
                project_id = int(cursor.lastrowid)
                for index, member in enumerate(project["members"]):
                    cursor.execute(
                        """
                        INSERT INTO people (display_name, source_key, status)
                        VALUES (%s, %s, 'provisional')
                        """,
                        (member["name"], f"json-import:{project_id}:{secrets.token_hex(8)}"),
                    )
                    person_id = int(cursor.lastrowid)
                    cursor.execute(
                        """
                        INSERT INTO project_members
                          (project_id, person_id, role, display_name_snapshot, sort_order,
                           contact_type, contact_value)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            project_id,
                            person_id,
                            member["role"],
                            member["name"],
                            index * 10,
                            member["contactType"],
                            member["contactValue"],
                        ),
                    )
                created["projects"].append({"id": project_id, "name": project["name"]})

            for resource in document["resources"]:
                cursor.execute(
                    """
                    INSERT INTO resources
                      (title, description, year, category, label, hot, downloads, image, resource_url)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        resource["title"],
                        resource["description"],
                        resource["year"],
                        resource["category"],
                        resource["label"],
                        resource["hot"],
                        resource["downloads"],
                        resource["image"],
                        resource["resourceUrl"],
                    ),
                )
                resource_id = int(cursor.lastrowid)
                created["resources"].append({"id": resource_id, "title": resource["title"]})

            for activity in document["photoActivities"]:
                cursor.execute(
                    """
                    INSERT INTO photo_activities
                      (activity, description, year, hot, downloads, sort_order, photo_dir)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        activity["activity"],
                        activity["description"],
                        activity["year"],
                        activity["hot"],
                        activity["downloads"],
                        activity["sortOrder"],
                        activity["photoDir"],
                    ),
                )
                activity_id = int(cursor.lastrowid)
                for photo in activity["photos"]:
                    cursor.execute(
                        """
                        INSERT INTO photo_items (activity_id, title, image_url, sort_order)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (activity_id, photo["title"], photo["src"], photo["sortOrder"]),
                    )
                created["photoActivities"].append({"id": activity_id, "activity": activity["activity"]})
    return {"summary": transfer_summary(document), "created": created}


def transfer_template() -> dict[str, Any]:
    """Return a small, valid template showing all supported entity shapes."""

    return {
        "format": TRANSFER_FORMAT,
        "version": TRANSFER_VERSION,
        "exportedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "projects": [
            {
                "name": "示例 CAS 项目",
                "category": "公益服务",
                "year": datetime.now().year,
                "assetDir": "/CAS/example/",
                "description": "项目简介",
                "cas": {"creativity": True, "activity": False, "service": True},
                "popularity": 0,
                "members": [
                    {"name": "示例成员", "role": "leader", "contactType": "wechat", "contactValue": "example"}
                ],
                "updates": [{
                    "id": "0123456789abcdef0123456789abcdef",
                    "content": "项目动态",
                    "images": ["activities/activity.jpg"],
                }],
            }
        ],
        "resources": [
            {
                "title": "示例资源",
                "description": "资源简介",
                "year": datetime.now().year,
                "category": "other",
                "label": "其他资源",
                "hot": 0,
                "downloads": 0,
                "image": "/uploads/example/cover.png",
                "resourceUrl": "/uploads/example/resource.pdf",
            }
        ],
        "photoActivities": [
            {
                "activity": "示例活动照片",
                "description": "活动简介",
                "year": datetime.now().year,
                "hot": 0,
                "downloads": 0,
                "sortOrder": 10,
                "photoDir": "/Photos/example/",
                "photos": [{"title": "照片 1", "src": "/Photos/example/001.jpg", "sortOrder": 10}],
            }
        ],
    }
