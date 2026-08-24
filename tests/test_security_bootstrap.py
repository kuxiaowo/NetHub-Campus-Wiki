"""生产认证配置和管理员初始化的回归测试。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.bootstrap_admin import AdminBootstrapError, create_initial_admin
from backend.config import validate_auth_secret_key
from backend.main import app


class AuthSecretValidationTest(unittest.TestCase):
    def test_rejects_missing_placeholder_and_short_secrets(self) -> None:
        for secret in (
            "",
            "dev-only-change-me",
            "change-this-to-a-long-random-secret",
            "too-short",
        ):
            with self.subTest(secret=secret):
                with self.assertRaises(RuntimeError):
                    validate_auth_secret_key(secret)

    def test_accepts_32_byte_secret(self) -> None:
        validate_auth_secret_key("0123456789abcdef0123456789abcdef")

    def test_api_startup_runs_runtime_validation(self) -> None:
        with patch(
            "backend.main.validate_runtime_settings",
            side_effect=RuntimeError("unsafe test configuration"),
        ):
            with self.assertRaisesRegex(RuntimeError, "unsafe test configuration"):
                with TestClient(app):
                    pass


class SchemaSecurityTest(unittest.TestCase):
    def test_fresh_schema_contains_no_user_accounts(self) -> None:
        schema_path = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"
        with tempfile.TemporaryDirectory() as temp_dir:
            connection = sqlite3.connect(Path(temp_dir) / "fresh.db")
            try:
                connection.executescript(schema_path.read_text(encoding="utf-8"))
                count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(count, 0)

    def test_migration_disables_only_unchanged_legacy_admin(self) -> None:
        migration_path = (
            Path(__file__).resolve().parents[1]
            / "sql"
            / "migrations"
            / "009_disable_legacy_default_admin.sql"
        )
        connection = sqlite3.connect(":memory:")
        try:
            connection.executescript(
                """
                CREATE TABLE users (
                  username TEXT,
                  password_hash TEXT,
                  role TEXT,
                  is_active INTEGER,
                  updated_at TEXT
                );
                INSERT INTO users VALUES
                  ('kuxiaowo',
                   'pbkdf2_sha256$260000$sFsreGUvs4sl9blJnDz7-A$pmlfVc0l5Y6jtu13kNneITspjRGRZKeQiZAc7g8gASw',
                   'admin', 1, NULL),
                  ('custom_admin', 'changed-hash', 'admin', 1, NULL);
                """
            )
            connection.executescript(migration_path.read_text(encoding="utf-8"))
            rows = connection.execute(
                "SELECT password_hash, role, is_active FROM users ORDER BY rowid"
            ).fetchall()
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        finally:
            connection.close()

        self.assertEqual(rows[0][1:], ("user", 0))
        self.assertEqual(rows[1][1:], ("admin", 1))
        self.assertEqual(version, 9)


class AdminBootstrapTest(unittest.TestCase):
    def test_creates_only_the_first_active_admin(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "bootstrap.db"
            with patch("backend.database.get_database_path", return_value=database_path):
                created = create_initial_admin(
                    "secure_admin",
                    "a-unique-admin-password",
                    "Secure Admin",
                )
                with self.assertRaises(AdminBootstrapError):
                    create_initial_admin(
                        "second_admin",
                        "another-admin-password",
                    )

            connection = sqlite3.connect(database_path)
            try:
                row = connection.execute(
                    "SELECT username, role, is_active FROM users WHERE id = ?",
                    (created["id"],),
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(row, ("secure_admin", "admin", 1))


if __name__ == "__main__":
    unittest.main()
