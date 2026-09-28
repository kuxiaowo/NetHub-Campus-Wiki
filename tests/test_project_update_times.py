"""Publication times must survive browsing and must never be invented."""

from pathlib import Path
import shutil
import sqlite3
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProjectUpdateTimeTest(unittest.TestCase):
    def test_existing_database_migration_keeps_view_and_content_times_separate(self):
        with sqlite3.connect(":memory:") as connection:
            connection.executescript((ROOT / "sql/schema.sql").read_text(encoding="utf-8"))
            connection.execute("ALTER TABLE projects ADD COLUMN asset_dir TEXT")
            connection.execute("""INSERT INTO projects
                (name, leader, members, category, year, description, updated_at, updates)
                VALUES ('Test', '', '', 'Test', 2026, 'Before', '2020-01-01', '[]')""")
            connection.commit()
            connection.executescript((ROOT / "sql/migrations/018_project_content_update_time.sql").read_text(encoding="utf-8"))
            connection.execute("UPDATE projects SET popularity = popularity + 1 WHERE id = 1")
            self.assertEqual(connection.execute("SELECT popularity, updated_at FROM projects").fetchone(), (1, '2020-01-01'))
            connection.execute("UPDATE projects SET description = 'After' WHERE id = 1")
            self.assertNotEqual(connection.execute("SELECT updated_at FROM projects").fetchone()[0], '2020-01-01')
            connection.execute("UPDATE projects SET updated_at = '2020-01-01' WHERE id = 1")
            connection.execute("UPDATE projects SET updates = '[{}]' WHERE id = 1")
            self.assertNotEqual(connection.execute("SELECT updated_at FROM projects").fetchone()[0], '2020-01-01')
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 18)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to run frontend behavior")
    def test_frontend_preserves_publication_time_and_leaves_missing_time_empty(self):
        script = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const source = fs.readFileSync('public/js/detail.js', 'utf8');
const context = {
  asArray: value => Array.isArray(value) ? value : [],
  cleanText: value => String(value || '').trim(),
  firstFilled: (...values) => values.find(value => value != null && String(value).trim()) || '',
  normalizeImages: () => [], normalizeVideos: () => [],
  safeDetailUrl: () => null, metricValue: () => null,
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function normalizeUpdates('), source.indexOf('function renderMediaImages(')), context);
const project = {createdAt: '2026-01-01', updatedAt: '2026-09-28', updates: [
  {content: 'Published', createdAt: '2026-06-06T12:00:00Z', updatedAt: '2026-09-28'},
  {content: 'Legacy', updatedAt: '2026-09-28'}, 'Old text'
]};
let result = context.normalizeUpdates(project);
assert.equal(result.find(item => item.content === 'Published').date, '2026-06-06T12:00:00Z');
assert.equal(result.find(item => item.content === 'Legacy').date, '');
assert.equal(result.find(item => item.content === 'Old text').date, '');
project.updatedAt = '2026-10-01';
assert.equal(JSON.stringify(context.normalizeUpdates(project)), JSON.stringify(result));
"""
        subprocess.run([shutil.which("node"), "-e", script], cwd=ROOT, check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
