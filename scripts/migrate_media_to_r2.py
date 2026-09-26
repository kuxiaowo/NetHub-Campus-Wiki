"""Safely migrate Campus Wiki business media through the frozen R2 Worker.

The command is dry-run by default. Pass ``--execute`` to write; it never
overwrites or deletes local/cloud objects. A checkpoint manifest is flushed
after every item so an interrupted run can resume without guessing.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.media_storage import (  # noqa: E402
    IMAGE_SUFFIXES,
    VIDEO_SUFFIXES,
    MediaConflictError,
    MediaStorageError,
    R2MediaStorage,
    build_image_thumbnail,
    normalize_logical_path,
    object_key_for_path,
    thumbnail_key_for_path,
)


BUSINESS_ROOTS = {
    "Photos", "CAS", "yearbook", "uploads", "documents", "teacher on stage",
}
_WINDOWS_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_ATOMIC_REPLACE_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8)


@contextmanager
def single_instance_lock(path: Path):
    """Hold a non-blocking process lock for the whole migration run."""

    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            if path.stat().st_size == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise SystemExit("已有媒体迁移进程正在运行，拒绝并发执行") from exc
            unlock = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise SystemExit("已有媒体迁移进程正在运行，拒绝并发执行") from exc
            unlock = lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        try:
            yield
        finally:
            unlock()
    finally:
        handle.close()


def _is_link_or_reparse(path: Path) -> bool:
    """Return whether *path* can redirect filesystem traversal.

    ``Path.is_symlink`` is sufficient on POSIX.  Windows directory junctions
    and other reparse points need an explicit attribute check on Python
    versions where ``Path.is_junction`` is unavailable.
    """

    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return bool(attributes & _WINDOWS_REPARSE_POINT)


def resolve_safe_source(path: Path, allowed_root: Path) -> Path:
    """Resolve an existing source without traversing a link/reparse point."""

    root = Path(os.path.abspath(os.fspath(allowed_root)))
    candidate = Path(os.path.abspath(os.fspath(path)))
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"源路径超出允许目录：{path}") from exc

    current = root
    for part in (Path(), *relative.parts):
        if part != Path():
            current /= part
        if _is_link_or_reparse(current):
            raise ValueError(f"源路径包含符号链接、目录联接或重解析点：{current}")

    root_resolved = root.resolve(strict=True)
    resolved = candidate.resolve(strict=True)
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError(f"源路径解析后超出允许目录：{path}")
    return resolved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2)
        output.flush()
        os.fsync(output.fileno())
    for delay in (*_ATOMIC_REPLACE_RETRY_DELAYS, None):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if delay is None:
                raise
            time.sleep(delay)


def migration_key(path: Path, public_root: Path) -> tuple[str | None, str | None]:
    logical = normalize_logical_path(path.relative_to(public_root).as_posix())
    parts = PurePosixPath(logical).parts
    if not parts or parts[0] not in BUSINESS_ROOTS:
        return None, "code_asset"
    if ".thumbs" in parts:
        thumb_index = parts.index(".thumbs")
        name = parts[-1]
        if name.endswith(".video.webp"):
            source_name = name.removesuffix(".video.webp")
            source = PurePosixPath(*parts[:thumb_index], source_name).as_posix()
            return thumbnail_key_for_path(source, video=True), None
        if name.endswith(".image.webp"):
            source_name = name.removesuffix(".image.webp")
            source = PurePosixPath(*parts[:thumb_index], source_name).as_posix()
            return thumbnail_key_for_path(source), None
        return None, "unknown_thumbnail"
    if path.suffix.casefold() in VIDEO_SUFFIXES:
        return None, "video_local"
    try:
        return object_key_for_path(logical), None
    except MediaStorageError:
        return None, "unsupported"


def verify_remote(storage: R2MediaStorage, key: str, expected_hash: str, expected_size: int) -> None:
    digest = hashlib.sha256()
    size = 0
    try:
        with requests.get(
            storage.download_key_url(key), stream=True,
            timeout=storage.timeout, allow_redirects=False,
        ) as response:
            response.raise_for_status()
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    size += len(chunk)
                    digest.update(chunk)
    except requests.RequestException as exc:
        raise MediaStorageError("迁移后回读失败") from exc
    if size != expected_size or digest.hexdigest() != expected_hash:
        raise MediaStorageError("迁移后回读哈希不一致", status_code=409, code="verification_failed")


def verify_existing_remote(
    storage: R2MediaStorage, key: str, expected_hash: str, expected_size: int,
    metadata_hash: str | None,
) -> None:
    # The Worker stores this hash only after verifying the uploaded body.
    if metadata_hash is not None:
        if not re.fullmatch(r"[a-fA-F0-9]{64}", metadata_hash) or metadata_hash.lower() != expected_hash:
            raise MediaStorageError("云端对象 SHA-256 元数据不一致", status_code=409, code="verification_failed")
        return
    verify_remote(storage, key, expected_hash, expected_size)


def checkpoint_matches(
    checkpoint: dict[str, Any] | None,
    key: str,
    digest: str,
    size: int,
    *,
    source_digest: str | None = None,
) -> bool:
    return bool(
        checkpoint
        and checkpoint.get("status") == "verified"
        and checkpoint.get("key") == key
        and checkpoint.get("size") == size
        and checkpoint.get("sha256") == digest
        and (source_digest is None or checkpoint.get("source_sha256") == source_digest)
    )


def migrate_object(
    storage: R2MediaStorage,
    source: Path,
    key: str,
    digest: str,
    size: int,
    record: dict[str, Any],
) -> str:
    """Upload or accept an identical object; never replace an existing key."""

    existing = storage.head_key(key)
    if existing:
        if existing.size != size:
            raise MediaConflictError("云端同名对象大小不同，拒绝覆盖")
        verify_existing_remote(storage, key, digest, size, existing.sha256)
        record.update(status="verified", action="same-object-skip", etag=existing.etag)
    else:
        uploaded = storage.put_key_file(key, source)
        verify_remote(storage, key, digest, size)
        record.update(status="verified", action="uploaded", etag=uploaded.etag)
    return str(record["action"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="迁移 Campus Wiki 业务媒体到私有 R2")
    parser.add_argument(
        "sources", nargs="*", type=Path, default=[Path("public/CAS")],
        help="待迁移文件或目录；默认 public/CAS 样本",
    )
    parser.add_argument(
        "--manifest", type=Path, default=Path(".media-migration-manifest.json"),
        help="断点清单路径",
    )
    parser.add_argument("--execute", action="store_true", help="实际上传；省略时仅 dry-run")
    parser.add_argument("--no-thumbnails", action="store_true", help="不为源图片生成缺失缩略图")
    return parser.parse_args()


def discover(sources: list[Path], allowed_root: Path) -> list[Path]:
    files: list[Path] = []
    for source in sources:
        candidate = PROJECT_ROOT / source if not source.is_absolute() else source
        try:
            resolved = resolve_safe_source(candidate, allowed_root)
        except (OSError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
        if resolved.is_file():
            files.append(resolved)
        elif resolved.is_dir():
            pending = [resolved]
            while pending:
                directory = pending.pop()
                for item in directory.iterdir():
                    try:
                        safe_item = resolve_safe_source(item, allowed_root)
                    except (OSError, ValueError) as exc:
                        raise SystemExit(str(exc)) from exc
                    if safe_item.is_dir():
                        pending.append(safe_item)
                    elif safe_item.is_file():
                        files.append(safe_item)
        else:
            raise SystemExit(f"源路径不存在：{source}")
    return sorted(set(files), key=lambda item: item.as_posix().casefold())


def main() -> int:
    args = parse_args()
    public_root = (PROJECT_ROOT / "public").resolve()
    manifest_path = (PROJECT_ROOT / args.manifest).resolve() if not args.manifest.is_absolute() else args.manifest.resolve()
    with single_instance_lock(manifest_path.parent / ".media-migration.lock"):
        return run(args, public_root, manifest_path)


def run(args: argparse.Namespace, public_root: Path, manifest_path: Path) -> int:
    try:
        previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"无法读取断点清单：{exc}") from exc
    manifest: dict[str, Any] = {
        "version": 2,
        "mode": "execute" if args.execute else "dry-run",
        "items": dict(previous.get("items") or {}),
        "thumbnails": dict(previous.get("thumbnails") or {}),
    }
    storage = R2MediaStorage() if args.execute else None
    failures = 0

    queue: list[tuple[Path, str]] = []
    for source in discover(args.sources, public_root):
        key, reason = migration_key(source, public_root)
        if not key:
            print(f"SKIP {reason} {source.relative_to(PROJECT_ROOT)}")
            continue
        queue.append((source, key))

    for source, key in queue:
        try:
            source = resolve_safe_source(source, public_root)
        except (OSError, ValueError) as exc:
            failures += 1
            print(f"FAIL unsafe-source {source}: {exc}", file=sys.stderr)
            continue
        relative = source.relative_to(PROJECT_ROOT).as_posix()
        digest = sha256_file(source)
        size = source.stat().st_size
        checkpoint = manifest["items"].get(relative)
        source_verified = False
        if checkpoint_matches(checkpoint, key, digest, size) and args.execute:
            try:
                assert storage is not None
                existing = storage.head_key(key)
                if existing is not None:
                    if existing.size != size:
                        raise MediaConflictError("断点对象大小已变化，拒绝覆盖")
                    verify_existing_remote(storage, key, digest, size, existing.sha256)
                    print(f"RESUME verified {relative}")
                    source_verified = True
            except (MediaStorageError, OSError) as exc:
                failures += 1
                failed = dict(checkpoint)
                failed.update(status="failed", error=str(exc))
                manifest["items"][relative] = failed
                atomic_json(manifest_path, manifest)
                print(f"FAIL {relative}: {exc}", file=sys.stderr)
                continue
        if not source_verified:
            record = {"key": key, "size": size, "sha256": digest, "status": "planned"}
            manifest["items"][relative] = record
            atomic_json(manifest_path, manifest)
            if not args.execute:
                print(f"PLAN {relative} -> {key} ({size} bytes)")
                continue
            try:
                assert storage is not None
                action = migrate_object(storage, source, key, digest, size, record)
                source_verified = True
                print(f"OK {action} {relative}")
            except (MediaStorageError, OSError) as exc:
                failures += 1
                record.update(status="failed", error=str(exc))
                print(f"FAIL {relative}: {exc}", file=sys.stderr)
            finally:
                atomic_json(manifest_path, manifest)

        if not source_verified:
            continue

        if (
            args.execute and not args.no_thumbnails
            and source.suffix.casefold() in IMAGE_SUFFIXES
            and ".thumbs" not in source.parts
        ):
            logical = normalize_logical_path(source.relative_to(public_root).as_posix())
            thumb_key = thumbnail_key_for_path(logical)
            thumb_records = manifest["thumbnails"]
            thumb_checkpoint = thumb_records.get(relative)
            if thumb_checkpoint and thumb_checkpoint.get("source_sha256") == digest:
                thumb_size = thumb_checkpoint.get("size")
                thumb_digest = thumb_checkpoint.get("sha256")
                if isinstance(thumb_size, int) and isinstance(thumb_digest, str) and checkpoint_matches(
                    thumb_checkpoint, thumb_key, thumb_digest, thumb_size, source_digest=digest
                ):
                    try:
                        existing = storage.head_key(thumb_key)
                        if existing is not None:
                            if existing.size != thumb_size:
                                raise MediaConflictError("断点缩略图大小已变化，拒绝覆盖")
                            verify_existing_remote(storage, thumb_key, thumb_digest, thumb_size, existing.sha256)
                            print(f"RESUME thumbnail verified {relative}")
                            continue
                    except (MediaStorageError, OSError) as exc:
                        failures += 1
                        failed = dict(thumb_checkpoint)
                        failed.update(status="failed", error=str(exc))
                        thumb_records[relative] = failed
                        atomic_json(manifest_path, manifest)
                        print(f"FAIL thumbnail {relative}: {exc}", file=sys.stderr)
                        continue

            thumb_record = {
                "key": thumb_key,
                "source_sha256": digest,
                "status": "planned",
            }
            thumb_records[relative] = thumb_record
            atomic_json(manifest_path, manifest)
            handle = tempfile.NamedTemporaryFile(suffix=".webp", delete=False)
            handle.close()
            thumbnail = Path(handle.name)
            try:
                build_image_thumbnail(source, thumbnail)
                thumb_digest = sha256_file(thumbnail)
                thumb_size = thumbnail.stat().st_size
                thumb_record.update(size=thumb_size, sha256=thumb_digest)
                action = migrate_object(
                    storage, thumbnail, thumb_key, thumb_digest, thumb_size, thumb_record
                )
                print(f"OK thumbnail {action} {relative}")
            except (MediaStorageError, OSError) as exc:
                failures += 1
                thumb_record.update(status="failed", error=str(exc))
                print(f"FAIL thumbnail {relative}: {exc}", file=sys.stderr)
            finally:
                atomic_json(manifest_path, manifest)
                thumbnail.unlink(missing_ok=True)

    print(f"完成：{len(queue)} 个候选，{failures} 个失败，模式={manifest['mode']}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
