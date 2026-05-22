"""资源中心数据访问模块。

资源中心包含普通资源和活动照片两类数据。这里负责把数据库里的 snake_case
字段整理成前端使用的 camelCase JSON，路由层只处理 HTTP 参数和响应模型。
"""

import re
from pathlib import Path
from typing import Any, Literal

from backend.database import get_db_connection

ResourceSort = Literal["hot", "new", "old", "download"]
PhotoSort = Literal["hot", "new", "old", "photoCount"]
BASE_DIR = Path(__file__).resolve().parents[1]
PUBLIC_DIR = BASE_DIR / "public"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
WINDOWS_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:/")


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


def _scan_photo_dir(photo_dir: str | None) -> list[dict[str, Any]]:
    resolved = _public_url_to_path(photo_dir)
    if resolved is None:
        return []
    target, relative = resolved
    if not target.exists() or not target.is_dir():
        return []

    photos = []
    for index, item in enumerate(sorted(target.iterdir(), key=lambda path: path.name.lower()), start=1):
        if not item.is_file() or item.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        item_relative = item.relative_to(PUBLIC_DIR.resolve()).as_posix()
        photos.append(
            {
                "id": index,
                "title": item.stem,
                "src": f"/{item_relative}",
                "sortOrder": index,
            }
        )
    return photos


def format_resource(row: dict[str, Any]) -> dict[str, Any]:
    """把 resources 表行转换为前端资源卡片需要的数据结构。"""

    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "year": row["year"],
        "category": row["category"],
        "label": row["label"],
        "type": row["type"],
        "hot": row["hot"],
        "downloads": row["downloads"],
        "image": row["image"],
        "resourceUrl": row["resource_url"],
        "createdAt": row.get("created_at"),
        "updatedAt": row.get("updated_at"),
    }


def list_resource_meta() -> dict[str, list[dict[str, str]] | list[int]]:
    """查询资源中心筛选器需要的分类和年份。"""

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT DISTINCT category, label FROM resources ORDER BY label ASC")
            categories = [
                {"value": row["category"], "label": row["label"]}
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
        where_parts.append("(title LIKE %s OR description LIKE %s OR label LIKE %s OR type LIKE %s)")
        keyword = f"%{search}%"
        params.extend([keyword, keyword, keyword, keyword])

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
    """查询活动照片，并把每个活动下的照片聚合成 images 数组。"""

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
        "hot": "pa.hot DESC, pa.created_at DESC",
        "new": "pa.year DESC, pa.created_at DESC",
        "old": "pa.year ASC, pa.created_at ASC",
        "photoCount": "photo_count DESC, pa.created_at DESC",
    }
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    sql = f"""
        SELECT
          pa.id,
          pa.activity,
          pa.description,
          pa.year,
          pa.hot,
          pa.photo_dir,
          pa.created_at,
          COUNT(pi.id) AS photo_count
        FROM photo_activities pa
        LEFT JOIN photo_items pi ON pi.activity_id = pa.id
        {where_sql}
        GROUP BY pa.id, pa.activity, pa.description, pa.year, pa.hot, pa.photo_dir, pa.created_at
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
                "sortOrder": row["sort_order"],
            }
        )

    result = []
    for row in activities:
        scanned_photos = _scan_photo_dir(row.get("photo_dir"))
        legacy_photos = photos_by_activity[row["id"]]
        images = scanned_photos or legacy_photos
        result.append(
            {
            "id": row["id"],
            "activity": row["activity"],
            "description": row.get("description") or "",
            "year": row["year"],
            "hot": row["hot"],
            "photoDir": row.get("photo_dir"),
            "images": images,
            "createdAt": row.get("created_at"),
            }
        )
    if sort == "photoCount":
        result.sort(key=lambda item: (len(item["images"]), item["createdAt"] or ""), reverse=True)
    return result
