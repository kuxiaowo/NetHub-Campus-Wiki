"""CAS project asset-directory rules and update normalization."""

from __future__ import annotations

import json
import re
import secrets
from pathlib import Path, PurePosixPath
from typing import Any

from backend.config import PROJECT_ROOT


PUBLIC_DIR = PROJECT_ROOT / "public"
CAS_DIR = PUBLIC_DIR / "CAS"
WINDOWS_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:[/\\]")
URL_SCHEME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
UPDATE_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
ICON_FILENAMES = (
    "icon.webp",
    "icon.png",
    "icon.jpg",
    "icon.jpeg",
    "icon.avif",
    "icon.gif",
)


class ProjectAssetError(ValueError):
    """Raised when a project asset directory or relative path is invalid."""


def new_update_id() -> str:
    return secrets.token_hex(16)


def normalize_update_id(value: Any, *, generate: bool = True) -> str:
    update_id = str(value or "").strip().lower()
    if UPDATE_ID_PATTERN.fullmatch(update_id):
        return update_id
    if not update_id and generate:
        return new_update_id()
    raise ProjectAssetError("动态 ID 必须是 32 位小写十六进制字符串")


def normalize_asset_dir(value: Any, *, require_exists: bool = False) -> str:
    """Return a canonical public URL rooted below ``public/CAS``."""

    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        raise ProjectAssetError("项目资源目录不能为空")
    if URL_SCHEME_PATTERN.match(raw) or WINDOWS_DRIVE_PATTERN.match(raw):
        raise ProjectAssetError("项目资源目录必须位于 public/CAS 下")
    relative = raw.strip("/")
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ProjectAssetError("项目资源目录不合法")
    if len(path.parts) < 2 or path.parts[0] != "CAS":
        raise ProjectAssetError("项目资源目录必须是 public/CAS 下的项目子目录")

    public_root = PUBLIC_DIR.resolve()
    cas_root = CAS_DIR.resolve()
    target = (public_root / Path(*path.parts)).resolve()
    if cas_root not in target.parents:
        raise ProjectAssetError("项目资源目录必须位于 public/CAS 下")
    if require_exists and (not target.exists() or not target.is_dir()):
        raise ProjectAssetError("项目资源目录不存在")
    return f"/{path.as_posix().rstrip('/')}/"


def asset_dir_path(asset_dir: Any, *, require_exists: bool = False) -> Path:
    normalized = normalize_asset_dir(asset_dir, require_exists=require_exists)
    return (PUBLIC_DIR / normalized.strip("/")).resolve()


def normalize_relative_image_path(
    value: Any,
    asset_dir: Any,
    *,
    require_exists: bool = False,
    allow_legacy: bool = False,
) -> str:
    """Normalize an image path relative to one CAS project's asset directory."""

    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        raise ProjectAssetError("动态图片路径不能为空")
    normalized_dir = normalize_asset_dir(asset_dir, require_exists=require_exists)

    # Old admin clients may still submit the resolved public URL. It is safe to
    # strip only the current project's exact directory prefix.
    if raw.startswith(normalized_dir):
        raw = raw[len(normalized_dir):]
    elif raw.startswith(("http://", "https://")):
        if allow_legacy:
            return raw
        raise ProjectAssetError("CAS 动态图片不允许使用外部 URL")
    elif raw.startswith("/"):
        if allow_legacy:
            return raw
        raise ProjectAssetError("动态图片必须使用项目目录内的相对路径")

    if URL_SCHEME_PATTERN.match(raw) or WINDOWS_DRIVE_PATTERN.match(raw):
        raise ProjectAssetError("动态图片必须使用项目目录内的相对路径")
    relative = PurePosixPath(raw)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts or "." in relative.parts:
        raise ProjectAssetError("动态图片相对路径不合法")
    if relative.suffix.lower() not in IMAGE_SUFFIXES:
        raise ProjectAssetError("动态图片格式不支持")

    root = asset_dir_path(normalized_dir, require_exists=require_exists)
    target = (root / Path(*relative.parts)).resolve()
    if root not in target.parents:
        raise ProjectAssetError("动态图片路径不能离开项目资源目录")
    if require_exists and (not target.exists() or not target.is_file()):
        raise ProjectAssetError(f"动态图片不存在：{relative.as_posix()}")
    return relative.as_posix()


def project_asset_url(asset_dir: Any, relative_path: Any) -> str | None:
    raw = str(relative_path or "").strip().replace("\\", "/")
    if not raw:
        return None
    if raw.startswith(("http://", "https://", "/")):
        return raw
    try:
        clean = normalize_relative_image_path(raw, asset_dir, allow_legacy=True)
        normalized_dir = normalize_asset_dir(asset_dir)
    except ProjectAssetError:
        return None
    return f"{normalized_dir}{clean}"


def project_icon_url(asset_dir: Any, legacy_icon: Any = None) -> str | None:
    if asset_dir:
        try:
            normalized_dir = normalize_asset_dir(asset_dir)
            root = asset_dir_path(normalized_dir)
            for filename in ICON_FILENAMES:
                if (root / filename).is_file():
                    return f"{normalized_dir}{filename}"
        except ProjectAssetError:
            pass
    return str(legacy_icon or "").strip() or None


def parse_updates(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def normalize_project_updates(
    value: Any,
    asset_dir: Any = None,
    *,
    require_files: bool = False,
    allow_legacy: bool = False,
    drop_empty: bool = True,
) -> list[dict[str, Any]]:
    """Return canonical stored updates with stable IDs and relative image paths."""

    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(parse_updates(value), start=1):
        metadata: dict[str, Any] = {}
        if isinstance(item, str):
            update_id = new_update_id()
            content = item.strip()
            raw_images: list[Any] = []
        elif isinstance(item, dict):
            update_id = normalize_update_id(item.get("id"))
            content = str(item.get("content") or "").strip()
            raw_images = item.get("images", [])
            if not isinstance(raw_images, list):
                raise ProjectAssetError(f"第 {index} 条动态的 images 必须是数组")
            author_name = str(item.get("authorName") or "").strip()
            author_role = str(item.get("authorRole") or "").strip().lower()
            created_at = str(item.get("createdAt") or "").strip()
            raw_author_person_id = item.get("authorPersonId")
            raw_author_user_id = item.get("authorUserId")
            if author_name:
                metadata["authorName"] = author_name
            if author_role in {"admin", "leader", "member"}:
                metadata["authorRole"] = author_role
            if created_at:
                metadata["createdAt"] = created_at
            if raw_author_person_id is not None:
                try:
                    author_person_id = int(raw_author_person_id)
                except (TypeError, ValueError):
                    author_person_id = 0
                if author_person_id > 0:
                    metadata["authorPersonId"] = author_person_id
            if raw_author_user_id is not None:
                try:
                    author_user_id = int(raw_author_user_id)
                except (TypeError, ValueError):
                    author_user_id = 0
                if author_user_id > 0:
                    metadata["authorUserId"] = author_user_id
        else:
            raise ProjectAssetError(f"第 {index} 条动态格式不正确")
        if update_id in seen_ids:
            raise ProjectAssetError(f"第 {index} 条动态的 ID 重复")
        seen_ids.add(update_id)

        images: list[str] = []
        seen_images: set[str] = set()
        for raw_image in raw_images:
            raw = str(raw_image or "").strip()
            if not raw or raw in seen_images:
                continue
            if asset_dir:
                image = normalize_relative_image_path(
                    raw,
                    asset_dir,
                    require_exists=require_files,
                    allow_legacy=allow_legacy,
                )
            elif allow_legacy and raw:
                image = raw
            else:
                raise ProjectAssetError("项目尚未配置资源目录，不能保存动态图片")
            if image not in seen_images:
                images.append(image)
                seen_images.add(image)
        if drop_empty and not content and not images:
            continue
        result.append({"id": update_id, "content": content, "images": images, **metadata})
    return result


def public_updates(value: Any, asset_dir: Any = None) -> list[dict[str, Any]]:
    updates = normalize_project_updates(value, asset_dir, allow_legacy=True)
    return [
        {
            "id": update["id"],
            "content": update["content"],
            "images": [
                url
                for image in update["images"]
                if (url := project_asset_url(asset_dir, image))
            ],
            **{
                key: update[key]
                for key in ("authorPersonId", "authorUserId", "authorName", "authorRole", "createdAt")
                if key in update
            },
        }
        for update in updates
    ]


def infer_asset_dir(icon: Any, updates: Any) -> str | None:
    """Infer ``/CAS/<project>/`` from legacy public URLs when possible."""

    candidates = [str(icon or "").strip()]
    for item in parse_updates(updates):
        if isinstance(item, dict):
            candidates.extend(str(image or "").strip() for image in item.get("images", []))
    for candidate in candidates:
        clean = candidate.replace("\\", "/")
        if not clean.startswith("/CAS/"):
            continue
        parts = PurePosixPath(clean.strip("/")).parts
        if len(parts) >= 3:
            try:
                return normalize_asset_dir(f"/CAS/{parts[1]}/")
            except ProjectAssetError:
                continue
    return None
