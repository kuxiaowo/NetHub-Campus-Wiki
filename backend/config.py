"""后端配置模块。

所有运行环境相关的值都集中在这里读取，避免在路由、数据库访问等业务代码中
直接调用 os.getenv。这样后续切换开发、测试、生产环境时，只需要调整 .env。
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MIN_AUTH_SECRET_BYTES = 32
_INSECURE_AUTH_SECRETS = {
    "dev-only-change-me",
    "change-this-to-a-long-random-secret",
}


@dataclass(frozen=True)
class Settings:
    """API 服务运行配置。

    frozen=True 表示配置对象创建后不允许修改，避免运行过程中被意外改写。
    """

    api_port: int = int(os.getenv("API_PORT", os.getenv("PORT", "3100")))
    database_path: str = os.getenv("DATABASE_PATH", "data/campus_wiki.db")
    auth_secret_key: str = os.getenv("AUTH_SECRET_KEY", "").strip()
    auth_token_expire_minutes: int = int(os.getenv("AUTH_TOKEN_EXPIRE_MINUTES", "120"))
    photo_dir_cache_minutes: int = int(os.getenv("PHOTO_DIR_CACHE_MINUTES", "5"))
    cors_origins: tuple[str, ...] = tuple(
        # CORS_ORIGINS 使用逗号分隔，便于同时允许 localhost 和 127.0.0.1。
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://127.0.0.1:3200,http://localhost:3200",
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

    validate_auth_secret_key(settings.auth_secret_key)


def get_database_path() -> Path:
    """返回 SQLite 文件的绝对路径。"""

    configured_path = Path(settings.database_path).expanduser()
    if configured_path.is_absolute():
        return configured_path
    return PROJECT_ROOT / configured_path
