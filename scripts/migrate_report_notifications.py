"""Apply Wiki migration 019 while rebuilding SQLite-to-D1 capture triggers.

Stop the Wiki API and mirror worker before running this command.  Delivery
remains disarmed until a fresh snapshot has been reconciled with D1.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from scripts import d1_mirror


MIGRATION = Path(__file__).resolve().parents[1] / "sql/migrations/019_report_notifications.sql"


def _statements(source: str) -> list[str]:
    statements: list[str] = []
    current = ""
    for line in source.splitlines(keepends=True):
        current += line
        if sqlite3.complete_statement(current):
            statement = current.strip()
            if statement.upper() not in {"BEGIN IMMEDIATE;", "COMMIT;"}:
                statements.append(statement)
            current = ""
    if current.strip():
        raise ValueError("Incomplete migration SQL")
    return statements


def migrate(database_path: Path, backup_path: Path) -> dict:
    if backup_path.exists():
        raise FileExistsError(backup_path)
    db = d1_mirror.connect(database_path, write=True)
    try:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version != 18:
            raise RuntimeError(f"Expected Wiki schema version 18, found {version}")
        d1_mirror.verify_capture(db)
        backup = d1_mirror.connect(backup_path, write=True)
        try:
            db.backup(backup)
            if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed")
            if backup.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Backup foreign key check failed")
        finally:
            backup.close()
        backup_path.chmod(0o600)

        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("UPDATE _sync_control SET ready=0 WHERE id=1")
            triggers = [
                row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB '_sync_*'"
                )
            ]
            for name in triggers:
                db.execute("DROP TRIGGER " + d1_mirror.quote(name))
            for statement in _statements(MIGRATION.read_text(encoding="utf-8")):
                db.execute(statement)
            for statement in d1_mirror.expected_triggers(db).values():
                db.execute(statement)
            d1_mirror.verify_capture(db)
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Migrated database integrity check failed")
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Migrated database foreign key check failed")
        return {"version": db.execute("PRAGMA user_version").fetchone()[0], "mirrorDisarmed": True}
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(migrate(args.db, args.backup)))
