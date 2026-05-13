"""后端配置模块。

所有运行环境相关的值都集中在这里读取，避免在路由、数据库访问等业务代码中
直接调用 os.getenv。这样后续切换开发、测试、生产环境时，只需要调整 .env。
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    """API 服务运行配置。

    frozen=True 表示配置对象创建后不允许修改，避免运行过程中被意外改写。
    """

    db_host: str = os.getenv("DB_HOST", "127.0.0.1")
    db_port: int = int(os.getenv("DB_PORT", "3306"))
    db_user: str = os.getenv("DB_USER", "root")
    db_password: str = os.getenv("DB_PASSWORD", "")
    db_name: str = os.getenv("DB_NAME", "campus_cas_forum")
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
