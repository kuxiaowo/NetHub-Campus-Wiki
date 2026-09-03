"""CAS project directory, icon and version-8 migration tests."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
import unittest

from PIL import Image

class ProjectAssetStorageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1] / "public" / "CAS" / "__asset_rules_test__"
        cls.root.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (4, 4), "red").save(cls.root / "icon.jpg")
        Image.new("RGB", (4, 4), "blue").save(cls.root / "icon.png")
        (cls.root / "activities").mkdir(exist_ok=True)
        Image.new("RGB", (4, 4), "green").save(cls.root / "activities" / "one.jpg")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_icon_priority_and_relative_resolution(self) -> None:
        from backend.project_assets import (
            normalize_asset_dir,
            normalize_relative_image_path,
            project_icon_url,
            public_updates,
        )

        asset_dir = "/CAS/__asset_rules_test__/"
        self.assertEqual(normalize_asset_dir(asset_dir, require_exists=True), asset_dir)
        self.assertEqual(project_icon_url(asset_dir), f"{asset_dir}icon.png")
        self.assertEqual(
            normalize_relative_image_path("activities/one.jpg", asset_dir, require_exists=True),
            "activities/one.jpg",
        )
        updates = [{"id": "a" * 32, "content": "测试", "images": ["activities/one.jpg"]}]
        self.assertEqual(public_updates(updates, asset_dir)[0]["images"], [f"{asset_dir}activities/one.jpg"])

    def test_paths_cannot_escape_cas_project_directory(self) -> None:
        from backend.project_assets import ProjectAssetError, normalize_asset_dir, normalize_relative_image_path

        with self.assertRaises(ProjectAssetError):
            normalize_asset_dir("/uploads/example/")
        with self.assertRaises(ProjectAssetError):
            normalize_asset_dir("/CAS/../uploads/")
        with self.assertRaises(ProjectAssetError):
            normalize_relative_image_path("../icon.png", "/CAS/__asset_rules_test__/")
        with self.assertRaises(ProjectAssetError):
            normalize_relative_image_path("https://example.com/photo.png", "/CAS/__asset_rules_test__/")

    def test_version_8_backfill_infers_directory_and_relative_paths(self) -> None:
        from backend.database import _backfill_project_assets, _dict_row_factory

        connection = sqlite3.connect(":memory:")
        connection.row_factory = _dict_row_factory
        connection.executescript(
            """
            CREATE TABLE projects (
              id INTEGER PRIMARY KEY,
              icon TEXT,
              updates TEXT
            );
            INSERT INTO projects (id, icon, updates)
            VALUES (
              1,
              '/CAS/__asset_rules_test__/icon.png',
              '[{"content":"旧动态","images":["/CAS/__asset_rules_test__/activities/one.jpg"]}]'
            );
            INSERT INTO projects (id, icon, updates)
            VALUES (2, 'https://example.com/icon.png', '[]');
            PRAGMA user_version = 7;
            """
        )
        migration = (
            Path(__file__).resolve().parents[1]
            / "sql"
            / "migrations"
            / "008_project_asset_directories.sql"
        ).read_text(encoding="utf-8")
        connection.executescript(migration)
        _backfill_project_assets(connection)

        migrated = connection.execute("SELECT * FROM projects WHERE id = 1").fetchone()
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()["user_version"], 8)
        self.assertEqual(migrated["asset_dir"], "/CAS/__asset_rules_test__/")
        updates = json.loads(migrated["updates"])
        self.assertRegex(updates[0]["id"], r"^[a-f0-9]{32}$")
        self.assertEqual(updates[0]["images"], ["activities/one.jpg"])
        unresolved = connection.execute("SELECT * FROM projects WHERE id = 2").fetchone()
        self.assertIsNone(unresolved["asset_dir"])
        self.assertEqual(unresolved["icon"], "https://example.com/icon.png")
        connection.close()


if __name__ == "__main__":
    unittest.main()
