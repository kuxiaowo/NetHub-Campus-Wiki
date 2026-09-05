"""生产认证配置和管理员初始化的回归测试。"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.bootstrap_admin import AdminBootstrapError, create_initial_admin
from backend.config import settings, validate_auth_secret_key, validate_runtime_settings
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

    def test_runtime_oidc_cookie_and_cors_configuration(self) -> None:
        valid = replace(
            settings,
            oidc_issuer="https://accounts.example.test",
            oidc_client_secret="s" * 48,
            oidc_redirect_uri="https://wiki.example.test/api/auth/callback",
            frontend_base_url="https://wiki.example.test",
            auth_cookie_secure=True,
            cors_origins=("https://wiki.example.test",),
        )
        with patch("backend.config.settings", valid):
            validate_runtime_settings()

        insecure_cookie = replace(valid, auth_cookie_secure=False)
        with (
            patch("backend.config.settings", insecure_cookie),
            self.assertRaisesRegex(RuntimeError, "AUTH_COOKIE_SECURE"),
        ):
            validate_runtime_settings()

        wrong_origin = replace(valid, cors_origins=("https://other.example.test",))
        with (
            patch("backend.config.settings", wrong_origin),
            self.assertRaisesRegex(RuntimeError, "FRONTEND_BASE_URL"),
        ):
            validate_runtime_settings()


class SchemaSecurityTest(unittest.TestCase):
    def test_fresh_schema_contains_no_seed_data(self) -> None:
        sql_root = Path(__file__).resolve().parents[1] / "sql"
        with tempfile.TemporaryDirectory() as temp_dir:
            connection = sqlite3.connect(Path(temp_dir) / "fresh.db")
            try:
                connection.executescript(
                    (sql_root / "schema.sql").read_text(encoding="utf-8")
                )
                for migration_path in sorted((sql_root / "migrations").glob("*.sql")):
                    connection.executescript(migration_path.read_text(encoding="utf-8"))
                counts = {
                    table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in (
                        "users",
                        "projects",
                        "project_categories",
                        "resources",
                        "photo_activities",
                        "photo_items",
                        "announcements",
                    )
                }
                version = connection.execute("PRAGMA user_version").fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(counts, {table: 0 for table in counts})
        self.assertEqual(version, 15)

    def test_v10_migration_archives_drafts_and_marks_deleted_users(self) -> None:
        sql_root = Path(__file__).resolve().parents[1] / "sql"
        with tempfile.TemporaryDirectory() as temp_dir:
            connection = sqlite3.connect(Path(temp_dir) / "upgrade.db")
            try:
                connection.executescript((sql_root / "schema.sql").read_text(encoding="utf-8"))
                for migration_path in sorted((sql_root / "migrations").glob("*.sql")):
                    if migration_path.name.startswith("010_"):
                        break
                    connection.executescript(migration_path.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO users (username, password_hash) VALUES ('migration_user', 'hash')"
                )
                connection.execute(
                    "INSERT INTO announcements (title, content, status) VALUES ('草稿', '正文', 'draft')"
                )
                connection.commit()
                connection.executescript(
                    (sql_root / "migrations" / "010_user_deletion_and_announcement_statuses.sql").read_text(encoding="utf-8")
                )
                status = connection.execute("SELECT status FROM announcements").fetchone()[0]
                columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "INSERT INTO announcements (title, content, status) VALUES ('非法', '正文', 'draft')"
                    )
                version = connection.execute("PRAGMA user_version").fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(status, "archived")
        self.assertIn("deleted_at", columns)
        self.assertEqual(version, 10)

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

    def test_oidc_migration_preserves_local_id_but_disables_legacy_login(self) -> None:
        sql_root = Path(__file__).resolve().parents[1] / "sql"
        with tempfile.TemporaryDirectory() as temp_dir:
            connection = sqlite3.connect(Path(temp_dir) / "oidc-upgrade.db")
            try:
                connection.executescript((sql_root / "schema.sql").read_text(encoding="utf-8"))
                for migration_path in sorted((sql_root / "migrations").glob("*.sql")):
                    if migration_path.name.startswith("014_"):
                        break
                    connection.executescript(migration_path.read_text(encoding="utf-8"))
                connection.execute(
                    """
                    INSERT INTO users (id, username, password_hash, display_name, role, is_active)
                    VALUES (42, 'local_developer', 'legacy-password-hash', 'Local Dev', 'admin', 1)
                    """
                )
                connection.commit()
                connection.executescript(
                    (sql_root / "migrations" / "014_nethub_accounts_oidc.sql").read_text(
                        encoding="utf-8"
                    )
                )
                user = connection.execute(
                    "SELECT id, username, password_hash, role, is_active, auth_sub FROM users WHERE id = 42"
                ).fetchone()
                archive = connection.execute(
                    "SELECT username, password_hash FROM legacy_local_accounts_archive WHERE user_id = 42"
                ).fetchone()
                version = connection.execute("PRAGMA user_version").fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(user[0], 42)
        self.assertTrue(user[1].startswith("legacy_disabled_42_"))
        self.assertEqual(user[2:], ("", "user", 0, None))
        self.assertEqual(archive, ("local_developer", "legacy-password-hash"))
        self.assertEqual(version, 14)


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
