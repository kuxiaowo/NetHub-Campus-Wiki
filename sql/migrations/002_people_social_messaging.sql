BEGIN IMMEDIATE;

ALTER TABLE users ADD COLUMN avatar_url TEXT;
ALTER TABLE users ADD COLUMN bio TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN messaging_permission TEXT NOT NULL DEFAULT 'everyone'
  CHECK (messaging_permission IN ('everyone', 'following', 'mutual', 'nobody'));
ALTER TABLE users ADD COLUMN campus_verified INTEGER NOT NULL DEFAULT 0
  CHECK (campus_verified IN (0, 1));
ALTER TABLE users ADD COLUMN last_seen_at TEXT;

CREATE TABLE people (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  display_name TEXT NOT NULL,
  avatar_url TEXT,
  school_identifier_digest TEXT UNIQUE,
  user_id INTEGER UNIQUE,
  source_key TEXT UNIQUE,
  status TEXT NOT NULL DEFAULT 'provisional'
    CHECK (status IN ('provisional', 'claimed', 'archived')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX idx_people_display_name ON people(display_name);
CREATE INDEX idx_people_status ON people(status);

CREATE TABLE project_members (
  project_id INTEGER NOT NULL,
  person_id INTEGER NOT NULL,
  role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('leader', 'member')),
  display_name_snapshot TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (project_id, person_id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE RESTRICT
);
CREATE INDEX idx_project_members_project ON project_members(project_id, sort_order, person_id);
CREATE INDEX idx_project_members_person ON project_members(person_id, project_id);

CREATE TABLE person_claims (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  person_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  note TEXT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
  reviewed_by INTEGER,
  reviewed_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX idx_person_claims_person ON person_claims(person_id, status, created_at);
CREATE INDEX idx_person_claims_user ON person_claims(user_id, status, created_at);
CREATE UNIQUE INDEX idx_person_claims_one_pending
  ON person_claims(person_id, user_id) WHERE status = 'pending';

CREATE TABLE user_follows (
  follower_id INTEGER NOT NULL,
  following_id INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (follower_id, following_id),
  CHECK (follower_id <> following_id),
  FOREIGN KEY (follower_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (following_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX idx_user_follows_following ON user_follows(following_id, follower_id);

CREATE TABLE user_blocks (
  blocker_id INTEGER NOT NULL,
  blocked_id INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (blocker_id, blocked_id),
  CHECK (blocker_id <> blocked_id),
  FOREIGN KEY (blocker_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (blocked_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX idx_user_blocks_blocked ON user_blocks(blocked_id, blocker_id);

CREATE TABLE conversations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  direct_key TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_message_id INTEGER,
  last_message_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_conversations_last_message ON conversations(last_message_at DESC, id DESC);

CREATE TABLE conversation_members (
  conversation_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  request_status TEXT NOT NULL DEFAULT 'accepted'
    CHECK (request_status IN ('pending', 'accepted', 'declined')),
  last_read_message_id INTEGER,
  hidden_at TEXT,
  muted INTEGER NOT NULL DEFAULT 0 CHECK (muted IN (0, 1)),
  joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (conversation_id, user_id),
  FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX idx_conversation_members_user ON conversation_members(user_id, request_status, conversation_id);

CREATE TABLE messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id INTEGER NOT NULL,
  sender_id INTEGER NOT NULL,
  message_type TEXT NOT NULL DEFAULT 'text' CHECK (message_type IN ('text', 'project')),
  body TEXT NOT NULL DEFAULT '',
  project_id INTEGER,
  client_message_id TEXT,
  reply_to_id INTEGER,
  recalled_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
  FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL,
  FOREIGN KEY (reply_to_id) REFERENCES messages(id) ON DELETE SET NULL,
  UNIQUE (sender_id, client_message_id)
);
CREATE INDEX idx_messages_conversation ON messages(conversation_id, id DESC);
CREATE INDEX idx_messages_sender_created ON messages(sender_id, created_at DESC);

CREATE TABLE message_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id INTEGER NOT NULL,
  reporter_id INTEGER NOT NULL,
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'resolved', 'dismissed')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  resolved_at TEXT,
  resolved_by INTEGER,
  FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
  FOREIGN KEY (reporter_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (resolved_by) REFERENCES users(id) ON DELETE SET NULL,
  UNIQUE (message_id, reporter_id)
);
CREATE INDEX idx_message_reports_status ON message_reports(status, created_at DESC);

CREATE TRIGGER people_set_updated_at AFTER UPDATE ON people
WHEN NEW.updated_at = OLD.updated_at BEGIN
  UPDATE people SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
CREATE TRIGGER person_claims_set_updated_at AFTER UPDATE ON person_claims
WHEN NEW.updated_at = OLD.updated_at BEGIN
  UPDATE person_claims SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

PRAGMA user_version = 2;
COMMIT;
