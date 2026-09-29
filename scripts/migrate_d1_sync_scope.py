"""Refresh SQLite capture triggers after changing the D1 mirror scope.

Stop the site's D1 mirror worker before running this command.  The application
database remains the source of truth; the migration keeps the existing outbox
and D1 rows intact.  The worker later records skipped events for excluded
tables so the D1 watermark can move forward without deleting those rows.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts import d1_mirror


def migrate(path: Path, backup: Path) -> dict:
    if backup.exists():
        raise FileExistsError(backup)

    connection = d1_mirror.connect(path, write=True)
    try:
        destination = d1_mirror.connect(backup, write=True)
        try:
            connection.backup(destination)
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed")
            if destination.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Backup foreign key check failed")
        finally:
            destination.close()
        backup.chmod(0o600)

        mirrored = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='_sync_control'"
        ).fetchone()
        if not mirrored:
            return {"mirrorInstalled": False, "excludedTables": sorted(d1_mirror.SYNC_EXCLUDED_TABLES)}

        connection.execute("BEGIN IMMEDIATE")
        try:
            triggers = [
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='trigger' AND name GLOB '_sync_*'"
                )
            ]
            for name in triggers:
                connection.execute("DROP TRIGGER " + d1_mirror.quote(name))
            for statement in d1_mirror.expected_triggers(connection).values():
                connection.execute(statement)
            d1_mirror.verify_capture(connection)
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise

        return {
            "mirrorInstalled": True,
            "droppedTriggers": len(triggers),
            "createdTriggers": len(d1_mirror.expected_triggers(connection)),
            "excludedTables": sorted(d1_mirror.SYNC_EXCLUDED_TABLES),
            "outboxPreserved": True,
        }
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(migrate(args.db, args.backup), sort_keys=True))
