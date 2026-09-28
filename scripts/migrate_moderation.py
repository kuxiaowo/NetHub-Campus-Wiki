"""Migrate offline serving SQLite and refresh D1 capture atomically.

Stop the site's API and mirror delivery before running. Delivery stays disarmed
until a fresh snapshot has been reconciled and its watermark confirmed.
"""

import argparse
import json
from pathlib import Path

from nethub_moderation.migration import apply
from scripts import d1_mirror


def migrate(path, site, backup):
    if backup.exists():
        raise FileExistsError(backup)
    connection = d1_mirror.connect(path, write=True)
    try:
        destination = d1_mirror.connect(backup, write=True)
        try:
            connection.backup(destination)
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed")
        finally:
            destination.close()
        backup.chmod(0o600)
        mirrored = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='_sync_control'"
        ).fetchone()
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("BEGIN IMMEDIATE")
        try:
            if mirrored:
                connection.execute("UPDATE _sync_control SET ready=0 WHERE id=1")
                triggers = [
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB '_sync_*'"
                    )
                ]
                for name in triggers:
                    connection.execute("DROP TRIGGER " + d1_mirror.quote(name))
            apply(connection, site)
            if mirrored:
                for sql in d1_mirror.expected_triggers(connection).values():
                    connection.execute(sql)
                d1_mirror.verify_capture(connection)
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        connection.execute("PRAGMA foreign_keys=ON")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Migrated database integrity check failed")
        return {
            "site": site,
            "version": connection.execute("PRAGMA user_version").fetchone()[0],
            "mirrorDisarmed": bool(mirrored),
        }
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--site", choices=["wiki", "cas"], required=True)
    args = parser.parse_args()
    print(json.dumps(migrate(args.db, args.site, args.backup)))
