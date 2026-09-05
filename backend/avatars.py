"""用户头像的校验、标准化存储与安全清理。"""

from __future__ import annotations

import io
import os
import secrets
from pathlib import Path

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from backend.config import settings
from backend.media import local_public_path

BASE_DIR = Path(__file__).resolve().parents[1]
AVATAR_ROOT = BASE_DIR / "public" / "uploads" / "avatars"
ALLOWED_AVATAR_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_AVATAR_SOURCE_PIXELS = 25_000_000


def _managed_avatar_path(url: str | None) -> Path | None:
    value = local_public_path(url)
    prefix = "uploads/avatars/"
    if value is None or not value.startswith(prefix):
        return None
    relative = value.removeprefix(prefix)
    raw_path = Path(relative)
    if not relative or raw_path.is_absolute() or raw_path.drive or ".." in raw_path.parts:
        return None
    root = AVATAR_ROOT.resolve()
    target = (root / raw_path).resolve()
    return target if root in target.parents else None


def managed_avatar_path(url: str | None) -> Path | None:
    """Resolve a legacy user avatar only when it is inside the managed avatar root."""

    return _managed_avatar_path(url)


def delete_managed_avatar(url: str | None) -> None:
    target = _managed_avatar_path(url)
    if target is None or not target.is_file():
        return
    target.unlink()
    try:
        target.parent.rmdir()
    except OSError:
        pass


async def store_avatar(user_id: int, upload: UploadFile) -> str:
    raw = await upload.read(settings.avatar_upload_max_bytes + 1)
    if len(raw) > settings.avatar_upload_max_bytes:
        max_mb = settings.avatar_upload_max_bytes // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"头像文件不能超过 {max_mb} MB")
    if not raw:
        raise HTTPException(status_code=422, detail="头像文件不能为空")

    try:
        with Image.open(io.BytesIO(raw)) as probe:
            if probe.format not in ALLOWED_AVATAR_FORMATS:
                raise HTTPException(status_code=422, detail="头像只支持 JPEG、PNG 或 WebP")
            if probe.width * probe.height > MAX_AVATAR_SOURCE_PIXELS:
                raise HTTPException(status_code=422, detail="头像图片像素尺寸过大")
            probe.verify()
        with Image.open(io.BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source)
            image.load()
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            size = settings.avatar_size_px
            normalized = ImageOps.fit(
                image,
                (size, size),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            output = io.BytesIO()
            normalized.save(output, format="WEBP", quality=settings.avatar_webp_quality, method=6)
    except HTTPException:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="头像文件不是有效图片") from exc

    root = AVATAR_ROOT.resolve()
    root.mkdir(parents=True, exist_ok=True)
    user_dir = (root / str(user_id)).resolve()
    if root not in user_dir.parents:
        raise HTTPException(status_code=422, detail="头像存储路径无效")
    user_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{secrets.token_hex(12)}.webp"
    target = user_dir / filename
    temporary = user_dir / f".{filename}.tmp"
    try:
        temporary.write_bytes(output.getvalue())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return f"/uploads/avatars/{user_id}/{filename}"
