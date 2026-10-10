-- Mirror-only offline DDL after backup, with delivery disarmed.
ALTER TABLE users ADD COLUMN muted_until INTEGER;
ALTER TABLE users ADD COLUMN is_muted INTEGER NOT NULL DEFAULT 0 CHECK(is_muted IN (0,1));
ALTER TABLE users ADD COLUMN mute_reason TEXT NOT NULL DEFAULT '';
CREATE TABLE project_updates (
 id TEXT PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 content TEXT NOT NULL, images TEXT NOT NULL DEFAULT '[]', metadata TEXT NOT NULL DEFAULT '{}',
 sort_order INTEGER NOT NULL DEFAULT 0, created_at TEXT, operator_id INTEGER REFERENCES users(id)
);
CREATE INDEX idx_project_updates_project ON project_updates(project_id,sort_order,id);
CREATE TABLE governance_audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER REFERENCES users(id), target_user_id INTEGER REFERENCES users(id),
 action TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
DROP TRIGGER IF EXISTS projects_set_updated_at;
ALTER TABLE projects DROP COLUMN updates;
-- Rebuild the D1 baseline from migrated SQLite; never mirror private submission/media/job tables.
