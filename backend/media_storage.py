"""Campus Wiki 业务媒体存储适配器。

生产环境只允许通过冻结的 Cloudflare Worker 访问私有 R2。开发与测试可显式
选择本地实现；两种实现共享同一套逻辑 public 路径，数据库无需保存云端 URL。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import os
import shutil
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO
from urllib.parse import quote

import requests
from PIL import Image, ImageOps, UnidentifiedImageError

from backend.config import PROJECT_ROOT, settings


EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
IMAGE_SUFFIXES = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"}
VIDEO_SUFFIXES = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
DOCUMENT_SUFFIXES = {
    ".doc", ".docx", ".md", ".pdf", ".ppt", ".pptx", ".txt",
    ".xls", ".xlsx", ".zip",
}
PUBLIC_R2_PREFIXES = {
    "Photos", "CAS", "avatars", "project-media", "thumbnails",
    "yearbook-pages", "video-thumbnails",
}
R2_PREFIXES = PUBLIC_R2_PREFIXES | {"yearbook-pdfs", "documents"}
_KEY_LOCKS: dict[str, threading.Lock] = {}
_KEY_LOCKS_GUARD = threading.Lock()


class MediaStorageError(RuntimeError):
    """A storage operation failed without exposing Worker internals to clients."""

    def __init__(self, message: str, *, status_code: int = 502, code: str = "storage_error") -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(message)


class MediaConflictError(MediaStorageError):
    def __init__(self, message: str = "同名媒体对象已存在") -> None:
        super().__init__(message, status_code=409, code="object_exists")


@dataclass(frozen=True)
class MediaObject:
    key: str
    size: int
    etag: str | None = None
    uploaded: str | float | None = None
    content_type: str | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class MediaPage:
    objects: list[MediaObject]
    next_cursor: str | None
    has_more: bool


def normalize_logical_path(value: str | None, *, allow_directory: bool = False) -> str:
    raw = unicodedata.normalize("NFC", str(value or "").strip().replace("\\", "/"))
    raw = raw.strip("/")
    if not raw:
        if allow_directory:
            return ""
        raise MediaStorageError("媒体路径不能为空", status_code=422, code="invalid_key")
    parts = raw.split("/")
    if any(
        not part
        or part in {".", ".."}
        or "%" in part
        or any(ord(char) < 32 or ord(char) == 127 for char in part)
        for part in parts
    ):
        raise MediaStorageError("媒体路径不合法", status_code=422, code="invalid_key")
    result = "/".join(parts)
    if len(result.encode("utf-8")) > 900:
        raise MediaStorageError("媒体路径过长", status_code=422, code="invalid_key")
    return result


def is_video_path(value: str | None) -> bool:
    try:
        return PurePosixPath(normalize_logical_path(value)).suffix.casefold() in VIDEO_SUFFIXES
    except MediaStorageError:
        return False


def object_key_for_path(value: str) -> str | None:
    """Map a stable public-relative path to the frozen Worker's object prefixes."""

    logical = normalize_logical_path(value)
    suffix = PurePosixPath(logical).suffix.casefold()
    if suffix in VIDEO_SUFFIXES:
        return None
    if suffix not in IMAGE_SUFFIXES | DOCUMENT_SUFFIXES:
        raise MediaStorageError("媒体文件类型不受 R2 网关支持", status_code=422, code="forbidden_extension")
    parts = logical.split("/")
    root = parts[0]
    tail = "/".join(parts[1:])
    if root == "uploads" and tail.startswith("avatars/"):
        return f"avatars/{tail.removeprefix('avatars/')}"
    if root == "uploads":
        return f"project-media/{logical}"
    if root == "yearbook":
        if suffix in IMAGE_SUFFIXES:
            return f"yearbook-pages/{tail}"
        if suffix == ".pdf":
            return f"yearbook-pdfs/{tail}"
        raise MediaStorageError(
            "Yearbook 只允许页面图片和 PDF",
            status_code=422,
            code="forbidden_extension",
        )
    if root == "yearbook-pages" and suffix not in IMAGE_SUFFIXES:
        raise MediaStorageError(
            "yearbook-pages 只允许页面图片",
            status_code=422,
            code="forbidden_extension",
        )
    if root == "yearbook-pdfs" and suffix != ".pdf":
        raise MediaStorageError(
            "yearbook-pdfs 只允许 PDF",
            status_code=422,
            code="forbidden_extension",
        )
    if root == "yearbook-thumbnails":
        raise MediaStorageError(
            "旧 Yearbook R2 前缀已禁用",
            status_code=422,
            code="invalid_key",
        )
    if root in R2_PREFIXES:
        return logical
    if root == "teacher on stage" and suffix in IMAGE_SUFFIXES:
        return f"video-thumbnails/{logical}"
    if suffix in IMAGE_SUFFIXES:
        return f"project-media/{logical}"
    if suffix in DOCUMENT_SUFFIXES:
        return f"documents/{logical}"
    raise MediaStorageError("媒体文件类型不受 R2 网关支持", status_code=422, code="forbidden_extension")


def object_prefix_for_directory(value: str, *, images: bool | None = None) -> str:
    logical = normalize_logical_path(value, allow_directory=True)
    if not logical:
        raise MediaStorageError("R2 列表必须指定业务目录", status_code=422, code="invalid_prefix")
    parts = logical.split("/")
    root = parts[0]
    tail = "/".join(parts[1:])
    suffix = f"{tail}/" if tail else ""
    if root == "yearbook-thumbnails":
        raise MediaStorageError(
            "旧 Yearbook R2 前缀已禁用",
            status_code=422,
            code="invalid_prefix",
        )
    if root == "uploads":
        if tail == "avatars" or tail.startswith("avatars/"):
            avatar_tail = tail.removeprefix("avatars").strip("/")
            return f"avatars/{avatar_tail + '/' if avatar_tail else ''}"
        return f"project-media/{logical}/"
    if root == "yearbook":
        prefix = "yearbook-pages" if images is not False else "yearbook-pdfs"
        return f"{prefix}/{suffix}"
    if root in R2_PREFIXES:
        return f"{logical}/"
    if root == "teacher on stage":
        return f"video-thumbnails/{logical}/"
    return f"project-media/{logical}/"


def logical_path_from_key(key: str) -> str:
    normalized = normalize_logical_path(key)
    if normalized.startswith("avatars/"):
        return f"uploads/avatars/{normalized.removeprefix('avatars/')}"
    if normalized.startswith("yearbook-pages/"):
        return f"yearbook/{normalized.removeprefix('yearbook-pages/')}"
    if normalized.startswith("yearbook-pdfs/"):
        return f"yearbook/{normalized.removeprefix('yearbook-pdfs/')}"
    if normalized.startswith("project-media/"):
        return normalized.removeprefix("project-media/")
    if normalized.startswith("documents/"):
        return normalized.removeprefix("documents/")
    if normalized.startswith("video-thumbnails/teacher on stage/"):
        return normalized.removeprefix("video-thumbnails/")
    return normalized


def thumbnail_key_for_path(value: str, *, video: bool = False) -> str:
    logical = normalize_logical_path(value)
    root = "video-thumbnails" if video else "thumbnails"
    return f"{root}/{logical}.{'video' if video else 'image'}.webp"


def _encode_key(key: str) -> str:
    normalized = normalize_logical_path(key)
    return "/".join(quote(part, safe="-._~") for part in normalized.split("/"))


def _canonical_query(params: dict[str, str]) -> str:
    return "&".join(
        f"{quote(key, safe='-._~')}={quote(value, safe='-._~')}"
        for key, value in sorted(params.items(), key=lambda item: (item[0], item[1]))
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build_image_thumbnail(source: Path, destination: Path) -> None:
    """Create the standard bounded WebP thumbnail used by both runtimes and migration."""

    try:
        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((settings.thumbnail_max_width, settings.thumbnail_max_height))
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGB")
            image.save(
                destination,
                "WEBP",
                quality=settings.thumbnail_webp_quality,
                method=settings.thumbnail_webp_method,
            )
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError) as exc:
        raise MediaStorageError("文件不是有效图片", status_code=422, code="invalid_image") from exc


def _key_lock(key: str) -> threading.Lock:
    with _KEY_LOCKS_GUARD:
        return _KEY_LOCKS.setdefault(key, threading.Lock())


class R2MediaStorage:
    def __init__(self) -> None:
        self.base_url = settings.r2_media_gateway_url.rstrip("/")
        self.secret = settings.r2_media_hmac_secret
        self.timeout = settings.r2_request_timeout_seconds
        if len(self.secret.encode("utf-8")) < 32:
            raise MediaStorageError("R2 HMAC 密钥未配置", status_code=503, code="storage_not_configured")

    def _signature(self, method: str, target: str, timestamp: str, body_hash: str) -> str:
        canonical = f"v1\n{method.upper()}\n{target}\n{timestamp}\n{body_hash}"
        return hmac.new(self.secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: bytes | BinaryIO | None = None,
        body_hash: str = EMPTY_SHA256,
        content_length: int = 0,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        query = _canonical_query(params or {})
        target = f"{path}?{query}" if query else path
        timestamp = str(int(time.time()))
        signed_headers = {
            "X-Media-Timestamp": timestamp,
            "X-Media-Content-SHA256": body_hash,
            "X-Media-Signature": self._signature(method, target, timestamp, body_hash),
            "Content-Length": str(content_length),
            **(headers or {}),
        }
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                params=params,
                data=body,
                headers=signed_headers,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise MediaStorageError("媒体网关暂时不可用") from exc
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            code = str(payload.get("error") or "storage_error")
            if response.status_code == 409 or code == "object_exists":
                raise MediaConflictError()
            if response.status_code == 404:
                raise MediaStorageError("媒体对象不存在", status_code=404, code=code)
            raise MediaStorageError(
                str(payload.get("message") or "媒体网关请求失败"),
                status_code=502 if response.status_code >= 500 else response.status_code,
                code=code,
            )
        return response

    def head_key(self, key: str) -> MediaObject | None:
        path = f"/internal/object/{_encode_key(key)}"
        try:
            response = self._request("HEAD", path)
        except MediaStorageError as exc:
            if exc.status_code == 404:
                return None
            raise
        return MediaObject(
            key=normalize_logical_path(key),
            size=int(response.headers.get("X-Media-Size", response.headers.get("Content-Length", "0"))),
            etag=response.headers.get("ETag"),
            uploaded=response.headers.get("X-Media-Uploaded"),
            content_type=response.headers.get("Content-Type"),
            sha256=response.headers.get("X-Media-SHA256"),
        )

    def head(self, logical_path: str) -> MediaObject | None:
        key = object_key_for_path(logical_path)
        return self.head_key(key) if key else None

    def list_key_prefix(self, prefix: str, *, cursor: str | None = None, limit: int = 50) -> MediaPage:
        if not 1 <= limit <= 100:
            raise MediaStorageError("分页大小必须在 1-100 之间", status_code=422, code="invalid_limit")
        params = {"prefix": prefix, "limit": str(limit)}
        if cursor:
            params["cursor"] = cursor
        response = self._request("GET", "/internal/list", params=params)
        payload = response.json()
        objects = [
            MediaObject(
                key=item["key"],
                size=int(item.get("size") or 0),
                etag=item.get("etag"),
                uploaded=item.get("uploaded"),
                content_type=(item.get("httpMetadata") or {}).get("contentType"),
                sha256=(item.get("customMetadata") or {}).get("sha256"),
            )
            for item in payload.get("objects", [])
        ]
        return MediaPage(objects, payload.get("nextCursor"), bool(payload.get("hasMore")))

    def list_directory(
        self,
        logical_prefix: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
        images: bool | None = None,
    ) -> MediaPage:
        return self.list_key_prefix(
            object_prefix_for_directory(logical_prefix, images=images),
            cursor=cursor,
            limit=limit,
        )

    def put_file(self, logical_path: str, source: Path, *, content_type: str | None = None) -> MediaObject:
        key = object_key_for_path(logical_path)
        if key is None:
            raise MediaStorageError("视频本体必须保存在本地", status_code=422, code="video_is_local")
        expected_type = mimetypes.guess_type(logical_path)[0]
        return self.put_key_file(key, source, content_type=expected_type or content_type)

    def put_key_file(self, key: str, source: Path, *, content_type: str | None = None) -> MediaObject:
        key = normalize_logical_path(key)
        size = source.stat().st_size
        digest = _sha256_file(source)
        guessed_type = content_type or mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        with _key_lock(key):
            existing = self.head_key(key)
            if existing:
                if existing.size == size and existing.sha256 == digest:
                    return existing
                raise MediaConflictError()
            if size <= settings.r2_direct_upload_max_bytes:
                path = f"/internal/object/{_encode_key(key)}"
                with source.open("rb") as body:
                    response = self._request(
                        "PUT", path, body=body, body_hash=digest, content_length=size,
                        headers={"Content-Type": guessed_type},
                    )
                payload = response.json()
                return MediaObject(key, size, payload.get("etag"), content_type=guessed_type, sha256=digest)
            return self._multipart_upload(key, source, guessed_type, digest)

    def _multipart_upload(self, key: str, source: Path, content_type: str, digest: str) -> MediaObject:
        path = f"/internal/multipart/{_encode_key(key)}"
        created = self._request("POST", path, headers={"X-Media-Content-Type": content_type}).json()
        upload_id = str(created["uploadId"])
        parts: list[dict[str, Any]] = []
        try:
            with source.open("rb") as body:
                part_number = 1
                while chunk := body.read(settings.r2_multipart_part_bytes):
                    part_hash = hashlib.sha256(chunk).hexdigest()
                    response = self._request(
                        "PUT",
                        f"{path}/part/{part_number}",
                        params={"uploadId": upload_id},
                        body=chunk,
                        body_hash=part_hash,
                        content_length=len(chunk),
                    )
                    item = response.json()
                    parts.append({"partNumber": part_number, "etag": item["etag"]})
                    part_number += 1
            completion = json.dumps({"parts": parts}, separators=(",", ":")).encode()
            response = self._request(
                "POST", path, params={"uploadId": upload_id}, body=completion,
                body_hash=hashlib.sha256(completion).hexdigest(), content_length=len(completion),
                headers={"Content-Type": "application/json"},
            )
        except Exception:
            try:
                self._request("DELETE", path, params={"uploadId": upload_id})
            except MediaStorageError:
                pass
            raise
        return MediaObject(key, source.stat().st_size, response.json().get("etag"), content_type=content_type, sha256=digest)

    def delete_key(self, key: str) -> None:
        self._request("DELETE", f"/internal/object/{_encode_key(key)}")

    def delete(self, logical_path: str) -> None:
        key = object_key_for_path(logical_path)
        if key:
            self.delete_key(key)

    def public_key_url(self, key: str) -> str:
        normalized = normalize_logical_path(key)
        if normalized.split("/", 1)[0] not in PUBLIC_R2_PREFIXES:
            raise MediaStorageError("该对象不能公开访问", status_code=403, code="private_object")
        return f"{self.base_url}/media/{_encode_key(normalized)}"

    def public_url(self, logical_path: str) -> str | None:
        key = object_key_for_path(logical_path)
        return self.public_key_url(key) if key else None

    def download_url(self, logical_path: str, *, method: str = "GET") -> str:
        key = object_key_for_path(logical_path)
        if key is None:
            raise MediaStorageError("本地视频不使用 R2 下载地址", status_code=422, code="video_is_local")
        return self.download_key_url(key, method=method)

    def download_key_url(self, key: str, *, method: str = "GET") -> str:
        key = normalize_logical_path(key)
        path = f"/download/{_encode_key(key)}"
        expires = str(int(time.time()) + settings.r2_download_url_seconds)
        canonical = f"v1\n{method.upper()}\n{path}\n{expires}\n{EMPTY_SHA256}"
        signature = hmac.new(self.secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        return f"{self.base_url}{path}?expires={expires}&sig={signature}"


class LocalMediaStorage:
    """Explicit development/test implementation rooted at ``public/``."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or PROJECT_ROOT / "public").resolve()

    def _path(self, logical_path: str) -> Path:
        logical = normalize_logical_path(logical_path)
        target = (self.root / Path(*logical.split("/"))).resolve()
        if self.root not in target.parents:
            raise MediaStorageError("媒体路径不合法", status_code=422, code="invalid_key")
        return target

    def head(self, logical_path: str) -> MediaObject | None:
        target = self._path(logical_path)
        if not target.is_file():
            return None
        stat = target.stat()
        return MediaObject(normalize_logical_path(logical_path), stat.st_size, uploaded=stat.st_mtime)

    def list_directory(
        self,
        logical_prefix: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
        images: bool | None = None,
    ) -> MediaPage:
        directory = self._path(logical_prefix)
        if not directory.is_dir():
            return MediaPage([], None, False)
        files = sorted((item for item in directory.iterdir() if item.is_file()), key=lambda item: item.name.casefold())
        if images is True:
            files = [item for item in files if item.suffix.casefold() in IMAGE_SUFFIXES]
        elif images is False:
            files = [item for item in files if item.suffix.casefold() in DOCUMENT_SUFFIXES]
        start = int(base64.urlsafe_b64decode(cursor + "==").decode()) if cursor else 0
        selected = files[start:start + limit]
        next_index = start + len(selected)
        next_cursor = base64.urlsafe_b64encode(str(next_index).encode()).decode().rstrip("=") if next_index < len(files) else None
        objects = [
            MediaObject(
                item.relative_to(self.root).as_posix(), item.stat().st_size,
                uploaded=item.stat().st_mtime,
                content_type=mimetypes.guess_type(item.name)[0],
            )
            for item in selected
        ]
        return MediaPage(objects, next_cursor, next_cursor is not None)

    def put_file(self, logical_path: str, source: Path, *, content_type: str | None = None) -> MediaObject:
        target = self._path(logical_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with source.open("rb") as incoming, target.open("xb") as output:
                shutil.copyfileobj(incoming, output, 1024 * 1024)
        except FileExistsError as exc:
            raise MediaConflictError() from exc
        return self.head(logical_path)  # type: ignore[return-value]

    def delete(self, logical_path: str) -> None:
        self._path(logical_path).unlink(missing_ok=True)

    def public_url(self, logical_path: str) -> str:
        logical = normalize_logical_path(logical_path)
        return "/" + "/".join(quote(part, safe="-._~") for part in logical.split("/"))

    def download_url(self, logical_path: str, *, method: str = "GET") -> str:
        return f"/api/files/{self.public_url(logical_path).lstrip('/')}"


def get_media_storage() -> R2MediaStorage | LocalMediaStorage:
    if settings.media_storage_backend == "local":
        if settings.app_environment == "production":
            raise MediaStorageError(
                "生产环境禁止使用本地媒体存储", status_code=503, code="storage_not_configured"
            )
        return LocalMediaStorage()
    return R2MediaStorage()


def encode_page_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    key = settings.r2_media_hmac_secret.encode() or b"local-test-cursor-key"
    signature = hmac.new(key, raw, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(raw + signature).decode().rstrip("=")


def decode_page_cursor(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(padded)
        raw, supplied = decoded[:-16], decoded[-16:]
        key = settings.r2_media_hmac_secret.encode() or b"local-test-cursor-key"
        expected = hmac.new(key, raw, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(supplied, expected):
            raise ValueError
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError
        return payload
    except (ValueError, TypeError, json.JSONDecodeError, base64.binascii.Error) as exc:
        raise MediaStorageError("分页游标无效", status_code=422, code="invalid_cursor") from exc
