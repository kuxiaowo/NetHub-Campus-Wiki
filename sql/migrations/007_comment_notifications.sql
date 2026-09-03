-- Persist reply and comment-like notifications without backfilling old activity.

BEGIN IMMEDIATE;

CREATE TABLE comment_notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL CHECK (kind IN ('reply', 'like')),
  recipient_id INTEGER NOT NULL,
  actor_id INTEGER NOT NULL,
  comment_id INTEGER NOT NULL,
  target_type TEXT NOT NULL CHECK (target_type IN ('announcement', 'project', 'resource')),
  target_id INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  read_at TEXT,
  UNIQUE (kind, recipient_id, actor_id, comment_id),
  FOREIGN KEY (recipient_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (actor_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX idx_comment_notifications_recipient_kind
  ON comment_notifications(recipient_id, kind, created_at DESC, id DESC);
CREATE INDEX idx_comment_notifications_unread
  ON comment_notifications(recipient_id, kind, id)
  WHERE read_at IS NULL;

PRAGMA user_version = 7;
COMMIT;
