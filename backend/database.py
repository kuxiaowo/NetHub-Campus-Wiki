"""数据库连接模块。

本项目暂时使用 PyMySQL 直连 MySQL。路由层不直接创建连接，而是统一通过
get_db_connection 获取连接，方便后续替换为连接池或 ORM。
"""

import pymysql
from pymysql.connections import Connection

from backend.config import settings


def get_db_connection() -> Connection:
    """创建 MySQL 连接。

    关键配置说明：
    - charset=utf8mb4：完整支持中文和 emoji。
    - DictCursor：查询结果直接返回 dict，方便组装 JSON。
    - autocommit=True：当前接口以只读为主，后续写接口也不容易忘记提交。
    """

    return pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )
