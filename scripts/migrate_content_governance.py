"""Offline v19 to v20 migration; stop application and mirror delivery first."""

import argparse
import importlib.util
import json
import sqlite3
from pathlib import Path

from backend.content_store import apply_governance_migration

MIGRATION = (
    Path(__file__).resolve().parents[1] / "sql/migrations/020_content_governance.sql"
)


def migrate(database_path, backup_path, mirror_module=None):
    database_path, backup_path = Path(database_path), Path(backup_path)
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    if backup_path.exists():
        raise FileExistsError(backup_path)
    db = sqlite3.connect(database_path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version != 19:
            raise RuntimeError(f"Expected Wiki schema 19, found {version}")
        mirrored = bool(
            db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='_sync_control'"
            ).fetchone()
        )
        mirror = None
        if mirrored:
            if not mirror_module:
                raise RuntimeError(
                    "Mirrored database requires verified --mirror-module"
                )
            spec = importlib.util.spec_from_file_location(
                "governance_mirror", mirror_module
            )
            mirror = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mirror)
            mirror.verify_capture(db)
        with backup_path.open("xb"):
            pass
        with sqlite3.connect(backup_path) as backup:
            db.backup(backup)
            if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed")
        backup_path.chmod(0o600)
        db.execute("BEGIN IMMEDIATE")
        try:
            if mirrored:
                db.execute("UPDATE _sync_control SET ready=0 WHERE id=1")
                names = [
                    r[0]
                    for r in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB '_sync_*'"
                    )
                ]
                for name in names:
                    db.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
            apply_governance_migration(
                db,
                MIGRATION.read_text(encoding="utf-8"),
                offline=True,
                transaction=False,
            )
            if mirrored:
                if any(
                    name.startswith(("_private_", "_moderation_"))
                    for name in mirror.tables(db)
                ):
                    raise RuntimeError(
                        "Mirror tool must exclude all _private_ and _moderation_ tables"
                    )
                for statement in mirror.expected_triggers(db).values():
                    db.execute(statement)
                mirror.verify_capture(db)
            db.commit()
        except BaseException:
            db.rollback()
            raise
        return {"version": 20, "mirrorDisarmed": mirrored}
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--mirror-module", type=Path)
    args = parser.parse_args()
    print(json.dumps(migrate(args.db, args.backup, args.mirror_module)))
