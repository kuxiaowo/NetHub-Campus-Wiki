"""SQLite 数据库连接与初始化模块。

业务代码原先使用 PyMySQL 的 ``%s`` 参数占位符。这里提供一层很薄的兼容封装，
将其转换为 SQLite 的 ``?``，从而让路由层保持稳定，迁移范围集中在数据层。
"""

import sqlite3
import threading
import re
import json
import hashlib
import hmac
import time
import uuid
import requests
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from backend.config import PROJECT_ROOT, get_database_path, settings
from backend.project_assets import (
    ProjectAssetError,
    infer_asset_dir,
    normalize_asset_dir,
    normalize_project_updates,
)

_SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema.sql"
_MIGRATIONS_PATH = PROJECT_ROOT / "sql" / "migrations"
_INITIALIZE_LOCK = threading.Lock()
_INITIALIZED_DATABASES: set[Path] = set()
_MIGRATION_PATTERN = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")


def _dict_row_factory(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
    return {description[0]: value for description, value in zip(cursor.description, row)}


def _translate_query(query: str) -> str:
    """把现有业务 SQL 的 PyMySQL 占位符转换为 SQLite 占位符。"""

    return query.replace("%s", "?")


class D1GatewayError(RuntimeError):
    """D1 gateway 请求失败或返回了数据库错误。"""

    def __init__(self, message: str, *, status: int | None = None, code: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class D1GatewayAdapter:
    """通过内部 Worker 网关访问 D1。

    网关协议故意保持很小：每次请求包含一个或多个参数化 SQL 语句，
    网关负责将 batch 映射为 D1 ``db.batch``。
    """

    def __init__(self, url: str, secret: str, timeout: float) -> None:
        if not url or not secret:
            raise RuntimeError("DATABASE_BACKEND=d1 时必须配置 D1_GATEWAY_URL 和 D1_GATEWAY_HMAC_SECRET")
        normalized_url = url.rstrip("/")
        self.url = (
            normalized_url
            if normalized_url.endswith("/internal/db")
            else normalized_url + "/internal/db"
        )
        self.secret, self.timeout = secret.encode(), timeout

    def _request(self, statements: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
        request_id = str(uuid.uuid4())
        timestamp = str(int(time.time()))
        payload = json.dumps(
            {"requestId": request_id, "timestamp": int(timestamp), "mode": mode, "statements": statements},
            separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
        body_hash = hashlib.sha256(payload).hexdigest()
        canonical = "\n".join(("v1", "POST", "/internal/db", request_id, timestamp, body_hash)).encode("utf-8")
        digest = hmac.new(self.secret, canonical, hashlib.sha256).hexdigest()
        try:
            response = requests.post(
                self.url, data=payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "NetHub-D1-Client/1.0",
                    "X-DB-Request-ID": request_id,
                    "X-DB-Timestamp": timestamp,
                    "X-DB-Signature": digest,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise D1GatewayError(f"D1 gateway 请求失败: {exc}") from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise D1GatewayError(
                "D1 gateway 返回了无效 JSON", status=response.status_code
            ) from exc
        if not response.ok or body.get("error"):
            message = body.get("message") or body.get("error") or "D1 gateway 请求失败"
            if response.status_code == 409 or body.get("error") == "database_conflict":
                raise sqlite3.IntegrityError(str(message))
            raise D1GatewayError(
                str(message),
                status=response.status_code,
                code=str(body.get("code") or body.get("error") or ""),
            )
        results = body.get("results")
        if not isinstance(results, list):
            raise D1GatewayError("D1 gateway 响应缺少 results")
        if len(results) != len(statements) or not all(isinstance(item, dict) for item in results):
            raise D1GatewayError("D1 gateway 响应的结果数量或格式无效")
        return results

    def execute(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any]:
        return self._request([{"sql": _translate_query(sql), "params": list(params)}], "single")[0]

    def batch(self, statements: Sequence[tuple[str, Sequence[Any]]]) -> list[dict[str, Any]]:
        payload = [{"sql": _translate_query(sql), "params": list(params)} for sql, params in statements]
        return self._request(payload, "batch")


class Cursor:
    """对 SQLite cursor 和 D1 gateway 结果的最小兼容封装。"""

    def __init__(self, cursor: sqlite3.Cursor | None = None, adapter: D1GatewayAdapter | None = None) -> None:
        self._cursor, self._adapter = cursor, adapter
        self._result: dict[str, Any] = {}

    def execute(self, query: str, parameters: Sequence[Any] | None = None) -> "Cursor":
        if self._adapter is not None:
            if query.strip().upper() in {"BEGIN IMMEDIATE", "BEGIN EXCLUSIVE", "BEGIN"}:
                raise RuntimeError("D1 不支持连接级事务；多语句原子写必须使用 Connection.batch()")
            self._result = self._adapter.execute(query, tuple(parameters or ()))
        else:
            self._cursor.execute(_translate_query(query), tuple(parameters or ()))
        return self

    def executemany(
        self,
        query: str,
        parameters: Iterable[Sequence[Any]],
    ) -> "Cursor":
        if self._adapter is not None:
            results = self._adapter.batch([(query, values) for values in parameters])
            self._batch_results = results
            changes = sum(int((item.get("meta") or {}).get("changes", 0)) for item in results)
            last_id = (results[-1].get("meta") or {}).get("last_row_id") if results else None
            self._result = {"rows": [], "meta": {"changes": changes, "last_row_id": last_id}}
        else:
            self._cursor.executemany(_translate_query(query), parameters)
        return self

    def fetchone(self) -> dict[str, Any] | None:
        if self._adapter is not None:
            rows = self._result.get("rows") or []
            return rows[0] if rows else None
        return self._cursor.fetchone()

    def fetchall(self) -> list[dict[str, Any]]:
        if self._adapter is not None:
            return list(self._result.get("rows") or [])
        return self._cursor.fetchall()

    @property
    def lastrowid(self) -> int | None:
        if self._adapter is not None:
            return (self._result.get("meta") or {}).get("last_row_id")
        return self._cursor.lastrowid

    @property
    def rowcount(self) -> int:
        if self._adapter is not None:
            return int((self._result.get("meta") or {}).get("changes", 0))
        return self._cursor.rowcount

    def close(self) -> None:
        if self._cursor is not None:
            self._cursor.close()

    def __enter__(self) -> "Cursor":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()


class Connection:
    """提供现有路由使用的连接 facade；后端可为 SQLite 或 D1。"""

    def __init__(self, connection: sqlite3.Connection | None = None, adapter: D1GatewayAdapter | None = None) -> None:
        self._connection, self._adapter = connection, adapter

    def cursor(self) -> Cursor:
        return Cursor(self._connection.cursor() if self._connection is not None else None, self._adapter)

    def batch(self, statements: Sequence[tuple[str, Sequence[Any]]]) -> list[dict[str, Any]]:
        if self._adapter is not None:
            return self._adapter.batch(statements)
        cursor = self._connection.cursor()
        try:
            results = []
            for query, params in statements:
                cursor.execute(_translate_query(query), tuple(params))
                results.append({"rows": cursor.fetchall(), "meta": {"changes": cursor.rowcount, "last_row_id": cursor.lastrowid}})
            self._connection.commit()
            return results
        finally:
            cursor.close()

    def commit(self) -> None:
        if self._connection is None:
            raise RuntimeError("D1 不支持 commit()；多语句原子写必须使用 Connection.batch()")
        self._connection.commit()

    def rollback(self) -> None:
        if self._connection is None:
            raise RuntimeError("D1 不支持 rollback()；多语句原子写必须使用 Connection.batch()")
        self._connection.rollback()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        try:
            if self._connection is not None:
                if exc_type is None:
                    self._connection.commit()
                else:
                    self._connection.rollback()
        finally:
            self.close()


def _open_connection(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        database_path,
        timeout=settings.database_connect_timeout_seconds,
        check_same_thread=False,
    )
    connection.row_factory = _dict_row_factory
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = FULL")
    connection.execute(f"PRAGMA busy_timeout = {settings.database_busy_timeout_ms}")
    connection.execute("PRAGMA recursive_triggers = OFF")
    return connection


def _migration_files() -> list[tuple[int, Path]]:
    migrations: list[tuple[int, Path]] = []
    if not _MIGRATIONS_PATH.exists():
        return migrations
    for path in _MIGRATIONS_PATH.iterdir():
        match = _MIGRATION_PATTERN.fullmatch(path.name)
        if path.is_file() and match:
            migrations.append((int(match.group(1)), path))
    return sorted(migrations, key=lambda item: item[0])


def _split_member_names(leader: str, members: str) -> list[str]:
    raw_names = [leader, *re.split(r"[,，、;\n]+", members or "")]
    result: list[str] = []
    seen: set[str] = set()
    for value in raw_names:
        name = str(value or "").strip()
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        result.append(name)
    return result


def _backfill_project_members(connection: sqlite3.Connection) -> None:
    """把旧 projects.leader/members 文本安全迁移为待绑定人员档案。

    不按姓名跨项目自动合并，避免重名成员被错误绑定。管理员可在人员管理中确认后合并。
    """

    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'project_members'"
    ).fetchone()
    if table is None:
        return

    projects = connection.execute(
        """
        SELECT p.id, p.leader, p.members
        FROM projects p
        WHERE NOT EXISTS (
          SELECT 1 FROM project_members pm WHERE pm.project_id = p.id
        )
        ORDER BY p.id
        """
    ).fetchall()
    for project in projects:
        leader_key = str(project["leader"] or "").strip().casefold()
        for index, name in enumerate(_split_member_names(project["leader"], project["members"])):
            source_key = f"legacy-project:{project['id']}:member:{index}"
            cursor = connection.execute(
                """
                INSERT INTO people (display_name, source_key, status)
                VALUES (?, ?, 'provisional')
                """,
                (name, source_key),
            )
            connection.execute(
                """
                INSERT INTO project_members
                  (project_id, person_id, role, display_name_snapshot, sort_order)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    project["id"],
                    cursor.lastrowid,
                    "leader" if name.casefold() == leader_key else "member",
                    name,
                    index * 10,
                ),
            )


def _backfill_project_assets(connection: sqlite3.Connection) -> None:
    """Upgrade legacy CAS asset URLs after migration 008 added ``asset_dir``."""

    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(projects)").fetchall()
    }
    if "asset_dir" not in columns:
        return

    projects = connection.execute(
        "SELECT id, icon, updates, asset_dir FROM projects ORDER BY id"
    ).fetchall()
    for project in projects:
        raw_asset_dir = project["asset_dir"]
        asset_dir = None
        if raw_asset_dir:
            try:
                asset_dir = normalize_asset_dir(raw_asset_dir)
            except ProjectAssetError:
                asset_dir = None
        if asset_dir is None:
            asset_dir = infer_asset_dir(project["icon"], project["updates"])

        try:
            updates = normalize_project_updates(
                project["updates"],
                asset_dir,
                allow_legacy=True,
            )
        except ProjectAssetError:
            # Preserve malformed legacy content for the compatibility formatter;
            # an administrator can repair it after assigning an asset directory.
            continue

        serialized = json.dumps(updates, ensure_ascii=False)
        if asset_dir != raw_asset_dir or serialized != (project["updates"] or "[]"):
            connection.execute(
                "UPDATE projects SET asset_dir = ?, updates = ? WHERE id = ?",
                (asset_dir, serialized, project["id"]),
            )


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
                user_version = connection.execute("PRAGMA user_version").fetchone()["user_version"]

            for migration_version, migration_path in _migration_files():
                if migration_version <= user_version:
                    continue
                if migration_version != user_version + 1:
                    raise RuntimeError(
                        f"数据库迁移版本不连续：当前 {user_version}，下一个文件是 {migration_path.name}"
                    )
                connection.executescript(migration_path.read_text(encoding="utf-8"))
                migrated_version = connection.execute("PRAGMA user_version").fetchone()["user_version"]
                if migrated_version != migration_version:
                    raise RuntimeError(f"迁移 {migration_path.name} 未正确更新 user_version")
                user_version = migrated_version

            _backfill_project_members(connection)
            _backfill_project_assets(connection)
            connection.commit()
            _INITIALIZED_DATABASES.add(resolved_path)
        finally:
            connection.close()


def get_db_connection() -> Connection:
    """返回配置的数据库连接。

    D1 生产路径不会创建本地文件、执行 WAL/busy_timeout 或运行 schema
    初始化；schema 由后续独立的 D1 migration 流程管理。
    """

    if settings.database_backend == "d1":
        return Connection(adapter=D1GatewayAdapter(
            settings.d1_gateway_url,
            settings.d1_gateway_hmac_secret,
            settings.d1_request_timeout_seconds,
        ))
    if settings.database_backend != "sqlite":
        raise RuntimeError(f"不支持的 DATABASE_BACKEND: {settings.database_backend!r}")

    database_path = get_database_path()
    _initialize_database(database_path)
    return Connection(_open_connection(database_path))
