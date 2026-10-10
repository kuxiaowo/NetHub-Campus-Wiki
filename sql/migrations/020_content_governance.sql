BEGIN IMMEDIATE;
ALTER TABLE users ADD COLUMN muted_until INTEGER;
ALTER TABLE users ADD COLUMN is_muted INTEGER NOT NULL DEFAULT 0 CHECK(is_muted IN (0,1));
ALTER TABLE users ADD COLUMN mute_reason TEXT NOT NULL DEFAULT '';
CREATE TABLE _private_content_submissions (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('update','profile')),
 target_id INTEGER NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id),
 content TEXT NOT NULL, media_ids TEXT NOT NULL DEFAULT '[]', metadata TEXT NOT NULL DEFAULT '{}',
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','review','published','rejected','withdrawn')),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 decision_note TEXT NOT NULL DEFAULT '', decided_by INTEGER REFERENCES users(id)
);
CREATE INDEX idx__private_content_submissions_author ON _private_content_submissions(user_id,created_at);
CREATE TABLE project_updates (
 id TEXT PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 content TEXT NOT NULL, images TEXT NOT NULL DEFAULT '[]', metadata TEXT NOT NULL DEFAULT '{}',
 sort_order INTEGER NOT NULL DEFAULT 0, created_at TEXT, operator_id INTEGER REFERENCES users(id)
);
CREATE INDEX idx_project_updates_project ON project_updates(project_id,sort_order,id);
CREATE TABLE _private_content_media (
 id TEXT PRIMARY KEY, submission_id TEXT NOT NULL REFERENCES _private_content_submissions(id) ON DELETE CASCADE,
 storage_key TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL, mime TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE _moderation_content_jobs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, submission_id TEXT NOT NULL UNIQUE REFERENCES _private_content_submissions(id) ON DELETE CASCADE,
 content_hash TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
 token TEXT NOT NULL DEFAULT '', ready_at REAL NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0,
 config_version INTEGER,
 result_json TEXT NOT NULL DEFAULT '{}', error_code TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_content_queue ON _moderation_content_jobs(state,ready_at,id);
CREATE TABLE governance_audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER REFERENCES users(id), target_user_id INTEGER REFERENCES users(id),
 action TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
-- Pending comments reuse the existing 'hidden' state; only approved content is 'visible'.
-- Dynamic JSON is migrated and removed by the migration finalizer before serving requests.
UPDATE _moderation_jobs SET state='cancelled',token='' WHERE state IN ('dispatch','queued','running');
PRAGMA user_version=20;
COMMIT;
