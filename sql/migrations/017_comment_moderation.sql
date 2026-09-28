BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS _moderation_jobs (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 comment_id INTEGER NOT NULL UNIQUE REFERENCES comments(id) ON DELETE CASCADE,
 content_hash TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'dispatch',
 attempts INTEGER NOT NULL DEFAULT 0,
 token TEXT NOT NULL DEFAULT '',
 ready_at REAL NOT NULL DEFAULT 0,
 lease_until REAL NOT NULL DEFAULT 0,
 result_json TEXT NOT NULL DEFAULT '{}',
 error_code TEXT NOT NULL DEFAULT '',
 config_version INTEGER,
 final_reasons TEXT NOT NULL DEFAULT '[]',
 final_note TEXT NOT NULL DEFAULT '',
 reviewed_by INTEGER,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_moderation_queue ON _moderation_jobs(state,ready_at,id);
CREATE TABLE IF NOT EXISTS system_notifications (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 recipient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 comment_id INTEGER NOT NULL,
 is_reply INTEGER NOT NULL,
 target_type TEXT NOT NULL,
 target_id INTEGER NOT NULL,
 target_title TEXT NOT NULL,
 reason_codes TEXT NOT NULL,
 reason_note TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 read_at TEXT,
 UNIQUE(recipient_id, comment_id)
);
CREATE INDEX IF NOT EXISTS idx_system_notifications_recipient ON system_notifications(recipient_id,id DESC);

PRAGMA user_version=17;
COMMIT;
