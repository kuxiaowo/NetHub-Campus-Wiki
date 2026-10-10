import json
import sqlite3
from pathlib import Path

import pytest

from scripts.migrate_content_governance import migrate

ROOT = Path(__file__).resolve().parents[1]


def legacy_database(path, updates):
    with sqlite3.connect(path) as db:
        db.executescript((ROOT / "sql/schema.sql").read_text(encoding="utf-8"))
        for file in sorted((ROOT / "sql/migrations").glob("*.sql")):
            if int(file.name.split("_", 1)[0]) < 20:
                db.executescript(file.read_text(encoding="utf-8"))
        db.execute(
            "INSERT INTO projects(id,name,leader,members,category,year,description,updates) VALUES(1,'historic','','[]','category',2026,'',?)",
            (updates,),
        )


def test_offline_upgrade_keeps_backup_and_public_ids(tmp_path):
    path, backup = tmp_path / "wiki.db", tmp_path / "backup.db"
    ident = "a" * 32
    legacy_database(
        path, json.dumps([{"id": ident, "content": "历史公开动态", "images": []}])
    )
    assert migrate(path, backup) == {"version": 20, "mirrorDisarmed": False}
    with sqlite3.connect(path) as db:
        assert "updates" not in {
            r[1] for r in db.execute("PRAGMA table_info(projects)")
        }
        row = db.execute("SELECT id,content,metadata FROM project_updates").fetchone()
        assert row[0] == "1:" + ident
        assert row[1] == "历史公开动态"
        assert json.loads(row[2])["publicId"] == ident
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 19
        assert db.execute("SELECT updates FROM projects").fetchone()[0]


def test_invalid_history_rolls_back_ddl_and_preserves_original(tmp_path):
    path, backup = tmp_path / "wiki.db", tmp_path / "backup.db"
    legacy_database(path, "invalid-json")
    with pytest.raises(ValueError):
        migrate(path, backup)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 19
        assert (
            db.execute("SELECT updates FROM projects").fetchone()[0] == "invalid-json"
        )
        assert not db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='project_updates'"
        ).fetchone()
