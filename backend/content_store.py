"""Normalized project updates, including deterministic legacy migration."""

from __future__ import annotations

import json
import sqlite3

from backend.database import get_db_connection
from backend.project_assets import normalize_project_updates, project_asset_url


def finalize_migration(connection, *, transaction=True, offline=False):
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(projects)")}
    if "updates" not in columns:
        return
    if (
        not offline
        and connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='_sync_control'"
        ).fetchone()
    ):
        raise RuntimeError("内容治理迁移必须先停镜像并离线执行，不能自动修改镜像结构")
    if transaction:
        connection.execute("BEGIN IMMEDIATE")
    try:
        for row in connection.execute(
            "SELECT id,updates,asset_dir FROM projects"
        ).fetchall():
            try:
                legacy_items = json.loads(row["updates"] or "[]")
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"项目 {row['id']} 的历史动态 JSON 无效，请先离线修复"
                ) from exc
            if not isinstance(legacy_items, list):
                raise ValueError(f"项目 {row['id']} 的历史动态必须是数组")
            items = normalize_project_updates(
                row["updates"], row["asset_dir"], allow_legacy=True
            )
            if len(items) != len(legacy_items):
                raise ValueError(
                    f"项目 {row['id']} 存在无法完整转换的历史动态，请先离线修复"
                )
            for index, item in enumerate(items):
                # Existing IDs are only unique within a project; avoid changing public IDs.
                metadata = {
                    k: v
                    for k, v in item.items()
                    if k not in {"id", "content", "images"}
                }
                ident = str(item["id"])
                connection.execute(
                    "INSERT INTO project_updates(id,project_id,content,images,metadata,sort_order,created_at) VALUES(?,?,?,?,?,?,?)",
                    (
                        f"{row['id']}:{ident}",
                        row["id"],
                        item["content"],
                        json.dumps(item["images"], ensure_ascii=False),
                        json.dumps({**metadata, "publicId": ident}, ensure_ascii=False),
                        index,
                        item.get("createdAt"),
                    ),
                )
        connection.execute("DROP TRIGGER IF EXISTS projects_set_updated_at")
        connection.execute("ALTER TABLE projects DROP COLUMN updates")
        connection.execute("""
CREATE TRIGGER projects_set_updated_at AFTER UPDATE OF name,leader,members,category,year,icon,description,media,cas_creativity,cas_activity,cas_service,asset_dir ON projects
WHEN NEW.updated_at=OLD.updated_at AND (
 NEW.name IS NOT OLD.name OR NEW.leader IS NOT OLD.leader OR NEW.members IS NOT OLD.members OR
 NEW.category IS NOT OLD.category OR NEW.year IS NOT OLD.year OR NEW.icon IS NOT OLD.icon OR
 NEW.description IS NOT OLD.description OR NEW.media IS NOT OLD.media OR
 NEW.cas_creativity IS NOT OLD.cas_creativity OR NEW.cas_activity IS NOT OLD.cas_activity OR
 NEW.cas_service IS NOT OLD.cas_service OR NEW.asset_dir IS NOT OLD.asset_dir)
BEGIN UPDATE projects SET updated_at=CURRENT_TIMESTAMP WHERE id=NEW.id; END;
""")
        if transaction:
            connection.commit()
    except Exception:
        if transaction:
            connection.rollback()
        raise


def apply_governance_migration(connection, source, *, offline=False, transaction=True):
    """DDL and legacy content conversion succeed or roll back together."""
    if transaction:
        connection.execute("BEGIN IMMEDIATE")
    try:
        statement = ""
        for line in source.splitlines(keepends=True):
            statement += line
            if sqlite3.complete_statement(statement):
                if statement.strip().upper() not in {"BEGIN IMMEDIATE;", "COMMIT;"}:
                    connection.execute(statement)
                statement = ""
        if statement.strip():
            raise ValueError("Incomplete governance migration SQL")
        finalize_migration(connection, transaction=False, offline=offline)
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Governance migration foreign key check failed")
        if transaction:
            connection.commit()
    except BaseException:
        if transaction:
            connection.rollback()
        raise


def list_updates(project_id, asset_dir=None, *, admin=False):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM project_updates WHERE project_id=%s ORDER BY sort_order,id",
                (project_id,),
            )
            rows = cursor.fetchall()
    result = []
    for row in rows:
        meta = json.loads(row["metadata"])
        images = json.loads(row["images"])
        if not admin:
            images = [
                value
                if value.startswith("/api/content-media/")
                else project_asset_url(asset_dir, value)
                for value in images
            ]
            images = [value for value in images if value]
        result.append(
            {
                "id": meta.pop("publicId", row["id"]),
                "content": row["content"],
                "images": images,
                **meta,
                **({"createdAt": row["created_at"]} if row["created_at"] else {}),
            }
        )
    return result


def write_update(conn, project_id, item, operator_id=None):
    """Insert a published update while holding the transaction's writer lock."""
    metadata = {k: v for k, v in item.items() if k not in {"id", "content", "images"}}
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COALESCE(MIN(sort_order),0)-1 AS next FROM project_updates WHERE project_id=%s",
            (project_id,),
        )
        position = cursor.fetchone()["next"]
        cursor.execute(
            "INSERT INTO project_updates(id,project_id,content,images,metadata,sort_order,created_at,operator_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                f"{project_id}:{item['id']}",
                project_id,
                item["content"],
                json.dumps(item.get("images", []), ensure_ascii=False),
                json.dumps({**metadata, "publicId": item["id"]}, ensure_ascii=False),
                position,
                item.get("createdAt"),
                operator_id,
            ),
        )
        cursor.execute(
            "UPDATE projects SET updated_at=CURRENT_TIMESTAMP WHERE id=%s",
            (project_id,),
        )


def replace_updates(conn, project_id, items, operator_id=None):
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM project_updates WHERE project_id=%s", (project_id,))
    for item in reversed(items):
        write_update(conn, project_id, item, operator_id)
