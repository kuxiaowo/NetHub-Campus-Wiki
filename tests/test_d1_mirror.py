"""Failure boundary tests for the SQLite to D1 outbox."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError

from scripts import d1_mirror, d1_reconcile

D1_META = """
CREATE TABLE _sync_events (
  seq INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE,
  payload_hash TEXT NOT NULL, applied_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE _sync_watermark (id INTEGER PRIMARY KEY CHECK(id=1), seq INTEGER NOT NULL);
INSERT INTO _sync_watermark(id,seq) VALUES(1,0);
"""


class LocalGateway:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.lose_confirmation_once = False
        self.unavailable = False

    def request(self, statements):
        if self.unavailable:
            raise URLError("network unavailable")
        self.db.execute("BEGIN")
        try:
            results = []
            for sql, params in statements:
                cursor = self.db.execute(sql, params)
                results.append(
                    {"rows": [dict(row) for row in cursor.fetchall()] if cursor.description else []}
                )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        if len(statements) > 1 and self.lose_confirmation_once:
            self.lose_confirmation_once = False
            raise URLError("confirmation lost")
        return results


class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.local = root / "local.sqlite3"
        self.remote = root / "d1.sqlite3"
        db = sqlite3.connect(self.local)
        db.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE views(
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                count INTEGER NOT NULL
            );
        """)
        db.close()
        remote = sqlite3.connect(self.remote)
        remote.executescript(
            """
            CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE views(
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                count INTEGER NOT NULL
            );
        """
            + D1_META
        )
        remote.close()
        d1_mirror.install(self.local)
        self.gateway = LocalGateway(self.remote)

    def tearDown(self):
        self.gateway.db.close()
        self.temp.cleanup()

    def _arm(self):
        db = d1_mirror.connect(self.local, write=True)
        db.execute("UPDATE _sync_control SET ready=1,baseline_seq=0 WHERE id=1")
        db.close()

    def _event(self):
        db = d1_mirror.connect(self.local)
        event = db.execute(
            "SELECT * FROM _sync_outbox WHERE acked_at IS NULL ORDER BY seq LIMIT 1"
        ).fetchone()
        db.close()
        return event

    def test_capture_rollback_and_cross_table_commit(self):
        db = sqlite3.connect(self.local)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN")
        db.execute("INSERT INTO users VALUES(1,'rolled back')")
        db.rollback()
        self.assertIsNone(self._event())
        db.execute("INSERT INTO users VALUES(1,'kept')")
        db.execute("INSERT INTO views VALUES(2,1,0)")
        db.commit()
        db.execute("UPDATE views SET count=count+1 WHERE id=2")
        db.commit()
        db.close()
        self._arm()
        d1_mirror.worker(self.local, self.gateway, once=True, poll_seconds=0)
        self.assertEqual(self.gateway.db.execute("SELECT count FROM views").fetchone()[0], 1)
        self.assertEqual(
            self.gateway.db.execute("SELECT seq FROM _sync_watermark").fetchone()[0], 3
        )
        db = d1_mirror.connect(self.local)
        self.assertEqual(d1_mirror.status(db)["pending"], 0)
        db.close()

    def test_lost_confirmation_retry_deduplicates_counter(self):
        db = sqlite3.connect(self.local)
        db.execute("INSERT INTO users VALUES(1,'user')")
        db.commit()
        db.close()
        self._arm()
        self.gateway.lose_confirmation_once = True
        with self.assertRaises(RuntimeError):
            d1_mirror.worker(self.local, self.gateway, once=True, poll_seconds=0)
        self.assertEqual(self.gateway.db.execute("SELECT count(*) FROM users").fetchone()[0], 1)
        self.assertEqual(
            self.gateway.db.execute("SELECT count(*) FROM _sync_events").fetchone()[0], 1
        )
        d1_mirror.worker(self.local, self.gateway, once=True, poll_seconds=0)
        self.assertEqual(self.gateway.db.execute("SELECT count(*) FROM users").fetchone()[0], 1)
        db = d1_mirror.connect(self.local)
        self.assertEqual(d1_mirror.status(db)["pending"], 0)
        db.close()

    def test_unavailable_then_resume_and_delete(self):
        db = sqlite3.connect(self.local)
        db.execute("INSERT INTO users VALUES(1,'user')")
        db.commit()
        db.close()
        self._arm()
        self.gateway.unavailable = True
        with self.assertRaises(RuntimeError):
            d1_mirror.worker(self.local, self.gateway, once=True, poll_seconds=0)
        self.assertIsNotNone(self._event())
        self.gateway.unavailable = False
        d1_mirror.worker(self.local, self.gateway, once=True, poll_seconds=0)
        db = sqlite3.connect(self.local)
        db.execute("DELETE FROM users WHERE id=1")
        db.commit()
        db.close()
        d1_mirror.worker(self.local, self.gateway, once=True, poll_seconds=0)
        self.assertEqual(self.gateway.db.execute("SELECT count(*) FROM users").fetchone()[0], 0)
        self.assertEqual(
            self.gateway.db.execute("SELECT seq FROM _sync_watermark").fetchone()[0], 2
        )

    def test_cascaded_delete_and_primary_key_change(self):
        db = sqlite3.connect(self.local)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO users VALUES(1,'user')")
        db.execute("INSERT INTO views VALUES(1,1,0)")
        db.commit()
        db.close()
        self._arm()
        d1_mirror.worker(self.local, self.gateway, once=True, poll_seconds=0)
        db = sqlite3.connect(self.local)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("DELETE FROM users WHERE id=1")
        db.commit()
        db.execute("INSERT INTO users VALUES(2,'renumber')")
        db.commit()
        db.execute("UPDATE users SET id=3 WHERE id=2")
        db.commit()
        db.close()
        d1_mirror.worker(self.local, self.gateway, once=True, poll_seconds=0)
        self.assertEqual([row[0] for row in self.gateway.db.execute("SELECT id FROM users")], [3])
        self.assertEqual(self.gateway.db.execute("SELECT COUNT(*) FROM views").fetchone()[0], 0)

    def test_schema_change_blocks_delivery(self):
        db = sqlite3.connect(self.local)
        db.execute("ALTER TABLE users ADD COLUMN email TEXT")
        db.close()
        with self.assertRaisesRegex(RuntimeError, "schema"):
            d1_mirror.worker(self.local, self.gateway, once=True, poll_seconds=0)

    def test_snapshot_baseline_then_replay_only_later_events(self):
        db = sqlite3.connect(self.local)
        db.execute("INSERT INTO users VALUES(1,'at snapshot')")
        db.commit()
        db.close()
        snapshot_path = Path(self.temp.name) / "snapshot.sqlite3"
        seq = d1_mirror.snapshot(self.local, snapshot_path)
        self.assertEqual(seq, 1)
        db = sqlite3.connect(self.local)
        db.execute("UPDATE users SET name='after snapshot' WHERE id=1")
        db.commit()
        db.close()
        result = d1_reconcile.reconcile(snapshot_path, self.gateway, "accounts", apply=True)
        self.assertTrue(result["applied"])
        self.assertEqual(
            self.gateway.db.execute("SELECT name FROM users").fetchone()[0], "at snapshot"
        )
        local = d1_mirror.connect(self.local, write=True)
        local.execute("UPDATE _sync_control SET ready=1,baseline_seq=? WHERE id=1", (seq,))
        local.close()
        d1_mirror.worker(self.local, self.gateway, once=True, poll_seconds=0)
        self.assertEqual(
            self.gateway.db.execute("SELECT name FROM users").fetchone()[0], "after snapshot"
        )
        self.assertEqual(
            self.gateway.db.execute("SELECT seq FROM _sync_watermark").fetchone()[0], 2
        )

    def test_bounded_replay_stops_at_snapshot_watermark(self):
        db = sqlite3.connect(self.local)
        db.execute("INSERT INTO users VALUES(1,'first')")
        db.commit()
        db.execute("UPDATE users SET name='second' WHERE id=1")
        db.commit()
        snapshot_path = Path(self.temp.name) / "bounded.sqlite3"
        self.assertEqual(d1_mirror.snapshot(self.local, snapshot_path), 2)
        db.execute("UPDATE users SET name='third' WHERE id=1")
        db.commit()
        db.close()
        self._arm()
        d1_mirror.worker(self.local, self.gateway, once=False, poll_seconds=0, until_seq=2)
        self.assertEqual(self.gateway.db.execute("SELECT name FROM users").fetchone()[0], "second")
        self.assertEqual(
            self.gateway.db.execute("SELECT seq FROM _sync_watermark").fetchone()[0], 2
        )
        self.assertTrue(d1_reconcile.verify(snapshot_path, self.gateway, "accounts")["matches"])
        local = d1_mirror.connect(self.local)
        self.assertEqual(d1_mirror.status(local)["pending"], 1)
        local.close()

    def test_todo_baseline_clears_retired_ip_values(self):
        root = Path(self.temp.name)
        local_path = root / "todo-local.sqlite3"
        remote_path = root / "todo-d1.sqlite3"
        local = sqlite3.connect(local_path)
        local.executescript(
            """
            CREATE TABLE operation_logs(id INTEGER PRIMARY KEY, action TEXT NOT NULL);
            CREATE TABLE installer_download_logs(id INTEGER PRIMARY KEY, action TEXT NOT NULL);
            INSERT INTO operation_logs VALUES(1,'edit');
            INSERT INTO installer_download_logs VALUES(1,'download');
            """
        )
        local.close()
        remote = sqlite3.connect(remote_path)
        remote.executescript(
            """
            CREATE TABLE operation_logs(
                id INTEGER PRIMARY KEY, action TEXT NOT NULL, ip TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE installer_download_logs(
                id INTEGER PRIMARY KEY, action TEXT NOT NULL, ip TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE visit_logs(id INTEGER PRIMARY KEY);
            CREATE TABLE registration_attempt_logs(id INTEGER PRIMARY KEY);
            INSERT INTO operation_logs VALUES(1,'edit','old-value');
            INSERT INTO installer_download_logs VALUES(1,'download','old-value');
            """
            + D1_META
        )
        remote.close()
        d1_mirror.install(local_path)
        snapshot_path = root / "todo-snapshot.sqlite3"
        d1_mirror.snapshot(local_path, snapshot_path)
        gateway = LocalGateway(remote_path)
        try:
            result = d1_reconcile.reconcile(snapshot_path, gateway, "todo", apply=True)
            self.assertTrue(result["applied"])
            for table in ("operation_logs", "installer_download_logs"):
                self.assertEqual(gateway.db.execute(f"SELECT ip FROM {table}").fetchone()[0], "")
        finally:
            gateway.db.close()

    def test_reconcile_keyset_pages_large_and_nullable_composite_keys(self):
        remote = self.gateway.db
        remote.executescript("""
            CREATE TABLE bulk(id INTEGER PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE composite(a TEXT, b INTEGER, value TEXT NOT NULL,
                                   PRIMARY KEY(a,b));
        """)
        remote.execute("BEGIN")
        remote.executemany(
            "INSERT INTO bulk VALUES(?,?)", ((i, str(i)) for i in range(451))
        )
        remote.executemany(
            "INSERT INTO composite VALUES(?,?,?)",
            ((a, i, str(i)) for a in (None, "x") for i in range(201)),
        )
        remote.execute("COMMIT")

        queries = []
        request = self.gateway.request

        def record(statements):
            queries.append(statements[0][0])
            return request(statements)

        self.gateway.request = record
        bulk = d1_reconcile.select_rows(self.gateway, "bulk", ["id", "value"], ["id"])
        composite = d1_reconcile.select_rows(
            self.gateway, "composite", ["a", "b", "value"], ["a", "b"]
        )
        self.assertEqual(len(bulk), 451)
        self.assertEqual(len(composite), 402)
        self.assertEqual(len(queries), 6)
        self.assertTrue(all("OFFSET" not in sql for sql in queries))
        self.assertIn('"id" > ?', queries[1])
        self.assertIn('"a" IS NOT NULL', queries[4])


if __name__ == "__main__":
    unittest.main()
