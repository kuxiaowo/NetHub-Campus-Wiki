"""The production migration keeps D1 capture consistent with Wiki schema 019."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from scripts import d1_mirror
from scripts.migrate_report_notifications import migrate


ROOT = Path(__file__).resolve().parents[1]


class ReportNotificationMigrationTest(unittest.TestCase):
    def test_migration_rebuilds_capture_and_preserves_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "wiki.sqlite3"
            backup = Path(directory) / "wiki-before-019.sqlite3"
            with closing(sqlite3.connect(database)) as db:
                db.executescript((ROOT / "sql/schema.sql").read_text(encoding="utf-8"))
                for path in sorted((ROOT / "sql/migrations").glob("[0-9]*_*.sql")):
                    if int(path.name[:3]) > 18:
                        continue
                    db.executescript(path.read_text(encoding="utf-8"))
            d1_mirror.install(database)

            result = migrate(database, backup)

            self.assertEqual(result, {"version": 19, "mirrorDisarmed": True})
            with closing(d1_mirror.connect(database)) as db:
                d1_mirror.verify_capture(db)
                self.assertEqual(db.execute("SELECT ready FROM _sync_control WHERE id=1").fetchone()[0], 0)
                self.assertIn("report_notifications", d1_mirror.tables(db))
            with closing(sqlite3.connect(backup)) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 18)


if __name__ == "__main__":
    unittest.main()
