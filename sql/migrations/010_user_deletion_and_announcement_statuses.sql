BEGIN IMMEDIATE;

ALTER TABLE users ADD COLUMN deleted_at TEXT;

DROP TRIGGER announcements_set_updated_at;
DROP INDEX idx_announcements_public;

CREATE TABLE announcements_v10 (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'published'
    CHECK (status IN ('published', 'archived')),
  is_pinned INTEGER NOT NULL DEFAULT 0 CHECK (is_pinned IN (0, 1)),
  view_count INTEGER NOT NULL DEFAULT 0,
  created_by INTEGER,
  published_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
);

INSERT INTO announcements_v10
  (id, title, summary, content, status, is_pinned, view_count, created_by,
   published_at, created_at, updated_at)
SELECT
  id,
  title,
  summary,
  content,
  CASE WHEN status = 'published' THEN 'published' ELSE 'archived' END,
  is_pinned,
  view_count,
  created_by,
  published_at,
  created_at,
  updated_at
FROM announcements;

DROP TABLE announcements;
ALTER TABLE announcements_v10 RENAME TO announcements;

CREATE INDEX idx_announcements_public
  ON announcements(status, is_pinned DESC, published_at DESC, id DESC);

CREATE TRIGGER announcements_set_updated_at AFTER UPDATE ON announcements
WHEN NEW.updated_at = OLD.updated_at BEGIN
  UPDATE announcements SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

PRAGMA user_version = 10;
COMMIT;
