PRAGMA foreign_keys = OFF;
BEGIN IMMEDIATE;

DROP TRIGGER IF EXISTS people_set_updated_at;

CREATE TABLE people_multiple_bindings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  display_name TEXT NOT NULL,
  avatar_url TEXT,
  school_identifier_digest TEXT UNIQUE,
  user_id INTEGER,
  source_key TEXT UNIQUE,
  status TEXT NOT NULL DEFAULT 'provisional'
    CHECK (status IN ('provisional', 'claimed', 'archived')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

INSERT INTO people_multiple_bindings
  (id, display_name, avatar_url, school_identifier_digest, user_id, source_key,
   status, created_at, updated_at)
SELECT
  id, display_name, avatar_url, school_identifier_digest, user_id, source_key,
  status, created_at, updated_at
FROM people;

DROP TABLE people;
ALTER TABLE people_multiple_bindings RENAME TO people;

CREATE INDEX idx_people_display_name ON people(display_name);
CREATE INDEX idx_people_status ON people(status);
CREATE INDEX idx_people_user ON people(user_id);

CREATE TRIGGER people_set_updated_at AFTER UPDATE ON people
WHEN NEW.updated_at = OLD.updated_at BEGIN
  UPDATE people SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

PRAGMA user_version = 15;
COMMIT;
PRAGMA foreign_keys = ON;
