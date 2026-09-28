ALTER TABLE auth_sessions ADD COLUMN turnstile_verified_at INTEGER;
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
