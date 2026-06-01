"""资源中心数据访问模块。

资源中心包含普通资源和活动照片两类数据。这里负责把数据库里的 snake_case
字段整理成前端使用的 camelCase JSON，路由层只处理 HTTP 参数和响应模型。
"""

import re
import time
from pathlib import Path
from typing import Any, Literal

from backend.config import settings
from backend.database import get_db_connection

ResourceSort = Literal["hot", "new", "old", "download"]
PhotoSort = Literal["hot", "new", "old", "photoCount", "download"]
ResourceMetric = Literal["hot", "downloads"]
BASE_DIR = Path(__file__).resolve().parents[1]
PUBLIC_DIR = BASE_DIR / "public"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
YEARBOOK_PDF_EXTENSION = ".pdf"
WINDOWS_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:/")
THUMB_DIR_NAME = ".thumbs"
THUMB_MAX_SIZE = (640, 640)
_PHOTO_DIR_CACHE: dict[str, dict[str, Any]] = {}
_HOT_TRACK: dict[tuple[str, int, int], float] = {}
HOT_THROTTLE_SECONDS = 5.0
_PHOTO_ACTIVITY_DOWNLOADS_COLUMN_READY = False


class YearbookResourceError(Exception):
    """Raised when a yearbook resource cannot be opened as a page directory."""

    def __init__(self, detail: str, status_code: int = 422) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def _public_url_to_path(value: str | None) -> tuple[Path, str] | None:
    """Resolve a public URL or public-relative path to a safe local directory."""

    raw_value = (value or "").strip().replace("\\", "/")
    if not raw_value:
        return None
    if "://" in raw_value or WINDOWS_DRIVE_PATTERN.match(raw_value):
        return None
    relative = raw_value.strip("/")
    raw_path = Path(relative)
    if raw_path.is_absolute() or raw_path.drive or ".." in raw_path.parts:
        return None

    public_root = PUBLIC_DIR.resolve()
    target = (public_root / relative).resolve()
    if target != public_root and public_root not in target.parents:
        return None
    return target, relative


def _photo_files(target: Path) -> list[Path]:
    return [
        item
        for item in sorted(target.iterdir(), key=lambda path: path.name.lower())
        if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS
    ]


def _natural_sort_key(path: Path) -> list[int | str]:
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", path.name)
    ]


def _public_file_url(item: Path) -> str:
    return f"/{item.relative_to(PUBLIC_DIR.resolve()).as_posix()}"


def yearbook_cover_url(resource_url: str | None) -> str | None:
    """Return the first image page URL for a public yearbook directory."""

    resolved = _public_url_to_path(resource_url)
    if resolved is None:
        return None
    target, _ = resolved
    if not target.exists() or not target.is_dir():
        return None
    for item in sorted(target.iterdir(), key=_natural_sort_key):
        if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS:
            return _public_file_url(item)
    return None


def _scan_photo_dir(
    photo_dir: str | None,
    *,
    cover_only: bool = False,
    count_only: bool = False,
) -> list[dict[str, Any]]:
    resolved = _public_url_to_path(photo_dir)
    if resolved is None:
        return []
    target, relative = resolved

    if not target.exists() or not target.is_dir():
        return []

    if count_only:
        return [{} for _ in _photo_files(target)]
    if cover_only:
        files = _photo_files(target)
        if not files:
            return []
        return [_format_photo_file(files[0], 1)]

    cached_photos = _get_cached_photo_dir(relative)
    if cached_photos is not None:
        return cached_photos

    photos = []
    for index, item in enumerate(_photo_files(target), start=1):
        photos.append(_format_photo_file(item, index))
    _set_cached_photo_dir(relative, photos)
    return photos


def _format_photo_file(item: Path, index: int) -> dict[str, Any]:
    item_relative = item.relative_to(PUBLIC_DIR.resolve()).as_posix()
    thumb_url = _ensure_thumbnail(item)
    return {
        "id": index,
        "title": item.stem,
        "src": f"/{item_relative}",
        "thumbSrc": thumb_url,
        "sortOrder": index,
    }


def _get_cached_photo_dir(relative: str) -> list[dict[str, Any]] | None:
    cache_minutes = settings.photo_dir_cache_minutes
    if cache_minutes <= 0:
        return None

    cache_entry = _PHOTO_DIR_CACHE.get(relative)
    if not cache_entry or cache_entry["expires_at"] <= time.monotonic():
        return None
    return [photo.copy() for photo in cache_entry["photos"]]


def _set_cached_photo_dir(relative: str, photos: list[dict[str, Any]]) -> None:
    cache_minutes = settings.photo_dir_cache_minutes
    if cache_minutes <= 0:
        _PHOTO_DIR_CACHE.pop(relative, None)
        return

    _PHOTO_DIR_CACHE[relative] = {
        "expires_at": time.monotonic() + cache_minutes * 60,
        "photos": [photo.copy() for photo in photos],
    }


def _ensure_thumbnail(source: Path) -> str | None:
    """Create a WebP thumbnail beside the source image when possible."""

    thumb_dir = source.parent / THUMB_DIR_NAME
    thumb_path = thumb_dir / f"{source.stem}.webp"
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError:
        return None

    try:
        if thumb_path.is_file() and thumb_path.stat().st_mtime >= source.stat().st_mtime:
            return f"/{thumb_path.relative_to(PUBLIC_DIR.resolve()).as_posix()}"

        thumb_dir.mkdir(exist_ok=True)
        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail(THUMB_MAX_SIZE)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGB")
            image.save(thumb_path, "WEBP", quality=82, method=6)
        return f"/{thumb_path.relative_to(PUBLIC_DIR.resolve()).as_posix()}"
    except (OSError, UnidentifiedImageError):
        return None


def photo_archive_url(photo_dir: str | None) -> str | None:
    """Return the same-name RAR URL when it exists inside a public photo directory."""

    resolved = _public_url_to_path(photo_dir)
    if resolved is None:
        return None
    target, relative = resolved
    folder_name = Path(relative.rstrip("/")).name
    if not folder_name:
        return None
    archive_file = target / f"{folder_name}.rar"
    if not archive_file.is_file():
        return None
    return f"/{relative.rstrip('/')}/{folder_name}.rar"


def format_photo_activity(row: dict[str, Any], legacy_photos: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the public activity card shape with directory-derived cover data."""

    scanned_photos = _scan_photo_dir(row.get("photo_dir"), cover_only=True)
    cover_images = scanned_photos or legacy_photos[:1]
    directory_photo_count = len(_scan_photo_dir(row.get("photo_dir"), count_only=True)) if row.get("photo_dir") else 0
    archive_url = photo_archive_url(row.get("photo_dir"))
    return {
        "id": row["id"],
        "activity": row["activity"],
        "description": row.get("description") or "",
        "year": row["year"],
        "hot": row["hot"],
        "downloads": row.get("downloads", 0),
        "sortOrder": row["sort_order"],
        "photoDir": row.get("photo_dir"),
        "archiveUrl": archive_url,
        "coverSrc": cover_images[0]["src"] if cover_images else None,
        "coverThumbSrc": cover_images[0].get("thumbSrc") if cover_images else None,
        "photoCount": directory_photo_count or row["photo_count"],
        "createdAt": row.get("created_at"),
    }


def format_resource(row: dict[str, Any]) -> dict[str, Any]:
    """把 resources 表行转换为前端资源卡片需要的数据结构。"""

    image = row["image"]
    if row["category"] == "yearbook":
        image = yearbook_cover_url(row.get("resource_url")) or image

    return {
        "id": row["id"],
        "title": row["title"],
        "description": row.get("description") or "",
        "year": row["year"],
        "category": row["category"],
        "label": row["label"],
        "hot": row["hot"],
        "downloads": row["downloads"],
        "image": image,
        "resourceUrl": row["resource_url"],
        "createdAt": row.get("created_at"),
        "updatedAt": row.get("updated_at"),
    }


def bump_resource_metric(resource_id: int, metric: ResourceMetric) -> dict[str, Any] | None:
    """Increment one public resource counter and return the updated resource."""

    column = {"hot": "hot", "downloads": "downloads"}[metric]
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"UPDATE resources SET {column} = {column} + 1 WHERE id = %s", (resource_id,))
            if cursor.rowcount == 0:
                return None
            cursor.execute("SELECT * FROM resources WHERE id = %s LIMIT 1", (resource_id,))
            row = cursor.fetchone()
    return format_resource(row) if row else None


def ensure_photo_activity_downloads_column() -> None:
    """Add the activity-level downloads counter for existing local databases."""

    global _PHOTO_ACTIVITY_DOWNLOADS_COLUMN_READY
    if _PHOTO_ACTIVITY_DOWNLOADS_COLUMN_READY:
        return

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS count
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'photo_activities'
                  AND COLUMN_NAME = 'downloads'
                """
            )
            if cursor.fetchone()["count"] == 0:
                cursor.execute(
                    """
                    ALTER TABLE photo_activities
                      ADD COLUMN downloads INT NOT NULL DEFAULT 0 COMMENT '下载次数' AFTER hot
                    """
                )
            cursor.execute(
                """
                SELECT COUNT(*) AS count
                FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'photo_activities'
                  AND INDEX_NAME = 'idx_photo_activity_downloads'
                """
            )
            if cursor.fetchone()["count"] == 0:
                cursor.execute(
                    """
                    CREATE INDEX idx_photo_activity_downloads
                      ON photo_activities (downloads)
                    """
                )
    _PHOTO_ACTIVITY_DOWNLOADS_COLUMN_READY = True


def bump_photo_activity_downloads(activity_id: int) -> dict[str, Any] | None:
    """Increment one activity archive download counter and return the updated activity."""

    ensure_photo_activity_downloads_column()
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE photo_activities SET downloads = downloads + 1 WHERE id = %s", (activity_id,))
            if cursor.rowcount == 0:
                return None
            cursor.execute(
                """
                SELECT pa.*, COUNT(pi.id) AS photo_count
                FROM photo_activities pa
                LEFT JOIN photo_items pi ON pi.activity_id = pa.id
                WHERE pa.id = %s
                GROUP BY
                  pa.id, pa.activity, pa.description, pa.year, pa.hot, pa.downloads,
                  pa.sort_order, pa.photo_dir, pa.created_at, pa.updated_at
                """,
                (activity_id,),
            )
            row = cursor.fetchone()
    return format_photo_activity(row, []) if row else None


def _hot_track_key(scope: str, item_id: int, user_id: int | None) -> tuple[str, int, int] | None:
    if user_id is None:
        return None
    return (scope, item_id, user_id)


def _can_track_hot(scope: str, item_id: int, user_id: int | None) -> bool:
    key = _hot_track_key(scope, item_id, user_id)
    if key is None:
        return True

    now = time.monotonic()
    previous = _HOT_TRACK.get(key)
    if previous is not None and now - previous < HOT_THROTTLE_SECONDS:
        return False
    return True


def _mark_hot_tracked(scope: str, item_id: int, user_id: int | None) -> None:
    key = _hot_track_key(scope, item_id, user_id)
    if key is None:
        return
    _HOT_TRACK[key] = time.monotonic()


def get_yearbook_detail(
    resource_id: int,
    *,
    track_view: bool = False,
    viewer_user_id: int | None = None,
) -> dict[str, Any]:
    """Return the scanned image pages and first PDF for a yearbook resource directory."""

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            if track_view and _can_track_hot("resource", resource_id, viewer_user_id):
                cursor.execute("UPDATE resources SET hot = hot + 1 WHERE id = %s", (resource_id,))
                if cursor.rowcount:
                    _mark_hot_tracked("resource", resource_id, viewer_user_id)
            cursor.execute("SELECT * FROM resources WHERE id = %s LIMIT 1", (resource_id,))
            row = cursor.fetchone()

    if row is None:
        raise YearbookResourceError("资源不存在", status_code=404)
    if row["category"] != "yearbook":
        raise YearbookResourceError("资源不是 Yearbook", status_code=404)

    resolved = _public_url_to_path(row.get("resource_url"))
    if resolved is None:
        raise YearbookResourceError("Yearbook 资源 URL 必须是 public 下的目录")

    target, _ = resolved
    if not target.exists() or not target.is_dir():
        raise YearbookResourceError("Yearbook 资源目录不存在")

    page_files = [
        item
        for item in sorted(target.iterdir(), key=_natural_sort_key)
        if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS
    ]
    if not page_files:
        raise YearbookResourceError("Yearbook 资源目录中没有图片页面")

    pdf_files = [
        item
        for item in sorted(target.iterdir(), key=_natural_sort_key)
        if item.is_file() and item.suffix.lower() == YEARBOOK_PDF_EXTENSION
    ]
    pages = [
        {
            "index": index,
            "title": item.stem,
            "src": _public_file_url(item),
        }
        for index, item in enumerate(page_files, start=1)
    ]

    return {
        "resource": format_resource(row),
        "pages": pages,
        "pdfUrl": _public_file_url(pdf_files[0]) if pdf_files else None,
    }


def list_resource_meta() -> dict[str, list[dict[str, Any]] | list[int]]:
    """查询资源中心筛选器需要的分类和年份。"""

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT value, label, sort_order
                FROM resource_categories
                WHERE is_active = 1
                ORDER BY sort_order ASC, id ASC
                """
            )
            categories = [
                {"value": row["value"], "label": row["label"], "sortOrder": row["sort_order"]}
                for row in cursor.fetchall()
            ]

            cursor.execute("SELECT DISTINCT year FROM resources ORDER BY year DESC")
            years = [row["year"] for row in cursor.fetchall()]

            cursor.execute("SELECT DISTINCT year FROM photo_activities ORDER BY year DESC")
            photo_years = [row["year"] for row in cursor.fetchall()]

    return {"categories": categories, "years": years, "photoYears": photo_years}


def list_resources(
    category: str | None = None,
    year: int | None = None,
    search: str | None = None,
    sort: ResourceSort = "hot",
) -> list[dict[str, Any]]:
    """按筛选条件查询资源列表。

    排序字段通过路由参数白名单限制，这里只选择固定 SQL 片段；筛选值全部使用参数
    绑定，避免用户输入参与 SQL 拼接。
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
        where_parts.append("(title LIKE %s OR description LIKE %s OR label LIKE %s)")
        keyword = f"%{search}%"
        params.extend([keyword, keyword, keyword])

    order_map = {
        "hot": "hot DESC, created_at DESC",
        "new": "year DESC, created_at DESC",
        "old": "year ASC, created_at ASC",
        "download": "downloads DESC, created_at DESC",
    }
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    sql = f"SELECT * FROM resources {where_sql} ORDER BY {order_map[sort]}, id DESC"

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()

    return [format_resource(row) for row in rows]


def list_photo_activities(
    year: int | None = None,
    search: str | None = None,
    sort: PhotoSort = "hot",
) -> list[dict[str, Any]]:
    """查询活动照片活动列表，不加载完整照片数组。"""

    ensure_photo_activity_downloads_column()
    where_parts = []
    params = []

    if year:
        where_parts.append("pa.year = %s")
        params.append(year)
    if search:
        where_parts.append("(pa.activity LIKE %s OR pa.description LIKE %s)")
        keyword = f"%{search}%"
        params.extend([keyword, keyword])

    order_map = {
        "hot": "pa.sort_order ASC, pa.hot DESC, pa.created_at DESC",
        "new": "pa.sort_order ASC, pa.year DESC, pa.created_at DESC",
        "old": "pa.sort_order ASC, pa.year ASC, pa.created_at ASC",
        "photoCount": "pa.sort_order ASC, photo_count DESC, pa.created_at DESC",
        "download": "pa.sort_order ASC, pa.downloads DESC, pa.created_at DESC",
    }
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    sql = f"""
        SELECT
          pa.id,
          pa.activity,
          pa.description,
          pa.year,
          pa.hot,
          pa.downloads,
          pa.sort_order,
          pa.photo_dir,
          pa.created_at,
          COUNT(pi.id) AS photo_count
        FROM photo_activities pa
        LEFT JOIN photo_items pi ON pi.activity_id = pa.id
        {where_sql}
        GROUP BY pa.id, pa.activity, pa.description, pa.year, pa.hot, pa.downloads, pa.sort_order, pa.photo_dir, pa.created_at
        ORDER BY {order_map[sort]}, pa.id DESC
    """

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            activities = cursor.fetchall()
            activity_ids = [row["id"] for row in activities]

            if not activity_ids:
                return []

            placeholders = ", ".join(["%s"] * len(activity_ids))
            cursor.execute(
                f"""
                SELECT id, activity_id, title, image_url, sort_order
                FROM photo_items
                WHERE activity_id IN ({placeholders})
                ORDER BY activity_id ASC, sort_order ASC, id ASC
                """,
                activity_ids,
            )
            photo_rows = cursor.fetchall()

    photos_by_activity: dict[int, list[dict[str, Any]]] = {activity_id: [] for activity_id in activity_ids}
    for row in photo_rows:
        photos_by_activity[row["activity_id"]].append(
            {
                "id": row["id"],
                "title": row["title"],
                "src": row["image_url"],
                "thumbSrc": None,
                "sortOrder": row["sort_order"],
            }
        )

    result = [format_photo_activity(row, photos_by_activity[row["id"]]) for row in activities]
    if sort in {"photoCount", "download"}:
        result.sort(
            key=lambda item: (
                item["sortOrder"],
                -item["photoCount"] if sort == "photoCount" else -item["downloads"],
                -(item["createdAt"].timestamp() if item["createdAt"] else 0),
            )
        )
    return result


def get_activity_photo_detail(
    activity_id: int,
    *,
    track_view: bool = False,
    viewer_user_id: int | None = None,
) -> dict[str, Any] | None:
    """Return one activity with photos, optionally counting a public view."""

    ensure_photo_activity_downloads_column()
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            if track_view and _can_track_hot("photo_activity", activity_id, viewer_user_id):
                cursor.execute("UPDATE photo_activities SET hot = hot + 1 WHERE id = %s", (activity_id,))
                if cursor.rowcount:
                    _mark_hot_tracked("photo_activity", activity_id, viewer_user_id)

            cursor.execute(
                """
                SELECT pa.*, COUNT(pi.id) AS photo_count
                FROM photo_activities pa
                LEFT JOIN photo_items pi ON pi.activity_id = pa.id
                WHERE pa.id = %s
                GROUP BY
                  pa.id, pa.activity, pa.description, pa.year, pa.hot, pa.downloads,
                  pa.sort_order, pa.photo_dir, pa.created_at, pa.updated_at
                """,
                (activity_id,),
            )
            activity = cursor.fetchone()
            if activity is None:
                return None

            cursor.execute(
                """
                SELECT id, title, image_url, sort_order
                FROM photo_items
                WHERE activity_id = %s
                ORDER BY sort_order ASC, id ASC
                """,
                (activity_id,),
            )
            photo_rows = cursor.fetchall()

    scanned_photos = _scan_photo_dir(activity.get("photo_dir"))
    if scanned_photos:
        photos = scanned_photos
    else:
        photos = [
            {
                "id": row["id"],
                "title": row["title"],
                "src": row["image_url"],
                "thumbSrc": None,
                "sortOrder": row["sort_order"],
            }
            for row in photo_rows
        ]
    return {"activity": format_photo_activity(activity, photos), "photos": photos}


def list_activity_photos(activity_id: int) -> list[dict[str, Any]] | None:
    """Return photos for one activity, using the per-directory cache when configured."""

    detail = get_activity_photo_detail(activity_id)
    return detail["photos"] if detail else None
