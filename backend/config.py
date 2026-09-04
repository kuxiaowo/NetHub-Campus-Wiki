"""后端运行配置。

可随部署调整的值统一从项目根目录的 ``.env`` 读取。资源类型、文件扩展名和
数据格式版本等程序契约仍保留在对应模块中，避免通过环境变量意外改变数据语义。
"""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

MIN_AUTH_SECRET_BYTES = 32
MEBIBYTE = 1024 * 1024
_INSECURE_AUTH_SECRETS = {
    "dev-only-change-me",
    "change-this-to-a-long-random-secret",
}


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} 必须是整数，当前值为 {raw_value!r}") from exc
    if value < minimum:
        raise RuntimeError(f"{name} 不能小于 {minimum}")
    return value


def _env_float(name: str, default: float, *, minimum: float = 0) -> float:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} 必须是数字，当前值为 {raw_value!r}") from exc
    if value < minimum:
        raise RuntimeError(f"{name} 不能小于 {minimum}")
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name, str(default)).strip().casefold()
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} 必须是 true/false，当前值为 {raw_value!r}")


_DEFAULT_API_PORT = _env_int("PORT", 3100, minimum=1)


@dataclass(frozen=True)
class Settings:
    """API 服务运行配置。

    frozen=True 表示配置对象创建后不允许修改，避免运行过程中被意外改写。
    """

    api_host: str = os.getenv("API_HOST", "0.0.0.0").strip()
    api_port: int = _env_int("API_PORT", _DEFAULT_API_PORT, minimum=1)
    api_reload: bool = _env_bool("API_RELOAD", False)
    public_media_base_url: str = os.getenv("PUBLIC_MEDIA_BASE_URL", "").strip().rstrip("/")
    database_path: str = os.getenv("DATABASE_PATH", "data/campus_wiki.db")
    database_connect_timeout_seconds: float = _env_float(
        "DATABASE_CONNECT_TIMEOUT_SECONDS", 5, minimum=0
    )
    database_busy_timeout_ms: int = _env_int("DATABASE_BUSY_TIMEOUT_MS", 5000)
    auth_secret_key: str = os.getenv("AUTH_SECRET_KEY", "").strip()
    auth_token_expire_minutes: int = _env_int("AUTH_TOKEN_EXPIRE_MINUTES", 120, minimum=1)
    photo_dir_cache_minutes: int = _env_int("PHOTO_DIR_CACHE_MINUTES", 5)
    upload_max_bytes: int = _env_int("UPLOAD_MAX_MB", 50, minimum=1) * MEBIBYTE
    project_photo_max_bytes: int = (
        min(_env_int("PROJECT_PHOTO_MAX_MB", 5, minimum=1), 5) * MEBIBYTE
    )
    avatar_upload_max_bytes: int = _env_int("AVATAR_UPLOAD_MAX_MB", 5, minimum=1) * MEBIBYTE
    avatar_size_px: int = _env_int("AVATAR_SIZE_PX", 512, minimum=64)
    avatar_webp_quality: int = _env_int("AVATAR_WEBP_QUALITY", 85, minimum=1)
    data_import_max_bytes: int = _env_int("DATA_IMPORT_MAX_MB", 5, minimum=1) * MEBIBYTE
    thumbnail_max_width: int = _env_int("THUMBNAIL_MAX_WIDTH", 640, minimum=1)
    thumbnail_max_height: int = _env_int("THUMBNAIL_MAX_HEIGHT", 640, minimum=1)
    thumbnail_webp_quality: int = _env_int("THUMBNAIL_WEBP_QUALITY", 82, minimum=1)
    thumbnail_webp_method: int = _env_int("THUMBNAIL_WEBP_METHOD", 6)
    video_thumbnail_timeout_seconds: float = _env_float(
        "VIDEO_THUMBNAIL_TIMEOUT_SECONDS", 20, minimum=0.1
    )
    resource_hot_throttle_seconds: float = _env_float(
        "RESOURCE_HOT_THROTTLE_SECONDS", 5, minimum=0
    )
    message_max_length: int = _env_int("MESSAGE_MAX_LENGTH", 2000, minimum=1)
    message_recall_window_seconds: int = _env_int(
        "MESSAGE_RECALL_WINDOW_SECONDS", 120
    )
    message_rate_per_minute: int = _env_int("MESSAGE_RATE_PER_MINUTE", 30, minimum=1)
    stream_ticket_ttl_seconds: int = _env_int("STREAM_TICKET_TTL_SECONDS", 60, minimum=1)
    comment_max_length: int = _env_int("COMMENT_MAX_LENGTH", 1000, minimum=1)
    comment_rate_per_minute: int = _env_int("COMMENT_RATE_PER_MINUTE", 10, minimum=1)
    cors_origins: tuple[str, ...] = tuple(
        # CORS_ORIGINS 使用逗号分隔；默认允许从任意网卡地址打开的前端。
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "*",
        ).split(",")
        if origin.strip()
    )


# 全局只创建一个 settings 实例，其他模块通过导入它读取配置。
settings = Settings()


def validate_auth_secret_key(secret: str) -> None:
    """拒绝缺失、公开占位或长度不足的 Token 签名密钥。"""

    normalized = secret.strip()
    if not normalized:
        raise RuntimeError(
            "AUTH_SECRET_KEY 未配置。请生成至少 32 字节的随机密钥后再启动后端。"
        )
    if normalized.casefold() in _INSECURE_AUTH_SECRETS:
        raise RuntimeError(
            "AUTH_SECRET_KEY 仍是公开占位值。请更换为至少 32 字节的随机密钥。"
        )
    if len(normalized.encode("utf-8")) < MIN_AUTH_SECRET_BYTES:
        raise RuntimeError(
            f"AUTH_SECRET_KEY 长度不足，UTF-8 编码后至少需要 {MIN_AUTH_SECRET_BYTES} 字节。"
        )


def validate_runtime_settings() -> None:
    """在 API 接受请求前验证与安全相关的运行配置。"""

    if not settings.api_host:
        raise RuntimeError("API_HOST 不能为空")
    if not 1 <= settings.api_port <= 65535:
        raise RuntimeError("API_PORT 必须在 1-65535 之间")
    if not 1 <= settings.thumbnail_webp_quality <= 100:
        raise RuntimeError("THUMBNAIL_WEBP_QUALITY 必须在 1-100 之间")
    if not 0 <= settings.thumbnail_webp_method <= 6:
        raise RuntimeError("THUMBNAIL_WEBP_METHOD 必须在 0-6 之间")
    if settings.public_media_base_url:
        media_url = urlsplit(settings.public_media_base_url)
        if (
            media_url.scheme not in {"http", "https"}
            or not media_url.netloc
            or media_url.query
            or media_url.fragment
        ):
            raise RuntimeError("PUBLIC_MEDIA_BASE_URL 必须是无查询参数的 http/https URL")
    validate_auth_secret_key(settings.auth_secret_key)


def get_database_path() -> Path:
    """返回 SQLite 文件的绝对路径。"""

    configured_path = Path(settings.database_path).expanduser()
    if configured_path.is_absolute():
        return configured_path
    return PROJECT_ROOT / configured_path
