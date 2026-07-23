"""SQLite 数据库连接与初始化模块。

业务代码原先使用 PyMySQL 的 ``%s`` 参数占位符。这里提供一层很薄的兼容封装，
将其转换为 SQLite 的 ``?``，从而让路由层保持稳定，迁移范围集中在数据层。
"""

import sqlite3
import threading
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from backend.config import PROJECT_ROOT, get_database_path

_SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema.sql"
_INITIALIZE_LOCK = threading.Lock()
_INITIALIZED_DATABASES: set[Path] = set()


def _dict_row_factory(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
    return {description[0]: value for description, value in zip(cursor.description, row)}


def _translate_query(query: str) -> str:
    """把现有业务 SQL 的 PyMySQL 占位符转换为 SQLite 占位符。"""

    return query.replace("%s", "?")


class Cursor:
    """对 sqlite3.Cursor 的最小兼容封装。"""

    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor

    def execute(self, query: str, parameters: Sequence[Any] | None = None) -> "Cursor":
        self._cursor.execute(_translate_query(query), tuple(parameters or ()))
        return self

    def executemany(
        self,
        query: str,
        parameters: Iterable[Sequence[Any]],
    ) -> "Cursor":
        self._cursor.executemany(_translate_query(query), parameters)
        return self

    def fetchone(self) -> dict[str, Any] | None:
        return self._cursor.fetchone()

    def fetchall(self) -> list[dict[str, Any]]:
        return self._cursor.fetchall()

    @property
    def lastrowid(self) -> int | None:
        return self._cursor.lastrowid

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    def close(self) -> None:
        self._cursor.close()

    def __enter__(self) -> "Cursor":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()


class Connection:
    """提供与现有调用方式兼容的 SQLite 连接。"""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def cursor(self) -> Cursor:
        return Cursor(self._connection.cursor())

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()


def _open_connection(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=5, check_same_thread=False)
    connection.row_factory = _dict_row_factory
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA recursive_triggers = OFF")
    return connection


def _initialize_database(database_path: Path) -> None:
    resolved_path = database_path.resolve()
    if resolved_path in _INITIALIZED_DATABASES:
        return

    with _INITIALIZE_LOCK:
        if resolved_path in _INITIALIZED_DATABASES:
            return

        connection = _open_connection(resolved_path)
        try:
            user_version = connection.execute("PRAGMA user_version").fetchone()["user_version"]
            if user_version == 0:
                connection.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
                connection.commit()
            _INITIALIZED_DATABASES.add(resolved_path)
        finally:
            connection.close()


def get_db_connection() -> Connection:
    """返回已启用外键、WAL 与自动初始化的 SQLite 连接。"""

    database_path = get_database_path()
    _initialize_database(database_path)
    return Connection(_open_connection(database_path))
