BEGIN IMMEDIATE;

ALTER TABLE comment_reports ADD COLUMN decision TEXT NOT NULL DEFAULT '';
ALTER TABLE comment_reports ADD COLUMN review_note TEXT NOT NULL DEFAULT '';
ALTER TABLE message_reports ADD COLUMN decision TEXT NOT NULL DEFAULT '';
ALTER TABLE message_reports ADD COLUMN review_note TEXT NOT NULL DEFAULT '';
ALTER TABLE system_notifications ADD COLUMN original_excerpt TEXT NOT NULL DEFAULT '';

CREATE TABLE report_notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  recipient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  content_type TEXT NOT NULL CHECK (content_type IN ('comment', 'message')),
  report_id INTEGER NOT NULL,
  original_excerpt TEXT NOT NULL DEFAULT '',
  decision TEXT NOT NULL CHECK (decision IN ('deleted', 'rejected')),
  note TEXT NOT NULL DEFAULT '',
  reason_codes TEXT NOT NULL DEFAULT '[]',
  audience TEXT NOT NULL DEFAULT 'reporter' CHECK (audience IN ('reporter', 'author')),
  target_type TEXT,
  target_id INTEGER,
  target_title TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  read_at TEXT,
  UNIQUE(content_type, report_id, recipient_id)
);
CREATE INDEX idx_report_notifications_recipient ON report_notifications(recipient_id, id DESC);

PRAGMA user_version = 19;
COMMIT;
