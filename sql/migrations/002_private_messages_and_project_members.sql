PRAGMA foreign_keys = ON;

CREATE TABLE direct_conversations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_low_id INTEGER NOT NULL,
  user_high_id INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK (user_low_id < user_high_id),
  UNIQUE (user_low_id, user_high_id),
  FOREIGN KEY (user_low_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (user_high_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX idx_direct_conversations_low ON direct_conversations(user_low_id, updated_at DESC);
CREATE INDEX idx_direct_conversations_high ON direct_conversations(user_high_id, updated_at DESC);

CREATE TABLE direct_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id INTEGER NOT NULL,
  sender_id INTEGER NOT NULL,
  content TEXT NOT NULL CHECK (length(trim(content)) BETWEEN 1 AND 2000),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  read_at TEXT,
  FOREIGN KEY (conversation_id) REFERENCES direct_conversations(id) ON DELETE CASCADE,
  FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX idx_direct_messages_conversation ON direct_messages(conversation_id, id DESC);
CREATE INDEX idx_direct_messages_unread ON direct_messages(conversation_id, read_at, sender_id);

CREATE TABLE project_members (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  display_name TEXT NOT NULL CHECK (length(trim(display_name)) BETWEEN 1 AND 80),
  role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('leader', 'member')),
  user_id INTEGER,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX idx_project_members_project ON project_members(project_id, sort_order, id);
CREATE UNIQUE INDEX uq_project_members_linked_user
ON project_members(project_id, user_id)
WHERE user_id IS NOT NULL;

CREATE TRIGGER project_members_set_updated_at AFTER UPDATE ON project_members
WHEN NEW.updated_at = OLD.updated_at BEGIN
  UPDATE project_members SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
CREATE TRIGGER direct_messages_touch_conversation AFTER INSERT ON direct_messages BEGIN
  UPDATE direct_conversations SET updated_at = NEW.created_at WHERE id = NEW.conversation_id;
END;
CREATE TRIGGER direct_messages_validate_sender BEFORE INSERT ON direct_messages
WHEN NOT EXISTS (
  SELECT 1
  FROM direct_conversations conversation
  WHERE conversation.id = NEW.conversation_id
    AND (conversation.user_low_id = NEW.sender_id OR conversation.user_high_id = NEW.sender_id)
) BEGIN
  SELECT RAISE(ABORT, 'message sender is not a conversation participant');
END;

INSERT INTO project_members (project_id, display_name, role, sort_order)
SELECT id, trim(leader), 'leader', 0
FROM projects
WHERE trim(COALESCE(leader, '')) <> '';

WITH RECURSIVE split(project_id, rest, member_name, sort_order) AS (
  SELECT id, replace(COALESCE(members, ''), '，', ',') || ',', '', 10
  FROM projects
  UNION ALL
  SELECT
    project_id,
    substr(rest, instr(rest, ',') + 1),
    trim(substr(rest, 1, instr(rest, ',') - 1)),
    sort_order + 10
  FROM split
  WHERE rest <> ''
)
INSERT INTO project_members (project_id, display_name, role, sort_order)
SELECT split.project_id, split.member_name, 'member', split.sort_order
FROM split
JOIN projects ON projects.id = split.project_id
WHERE split.member_name <> ''
  AND lower(split.member_name) <> lower(trim(projects.leader))
  AND NOT EXISTS (
    SELECT 1
    FROM project_members existing
    WHERE existing.project_id = split.project_id
      AND lower(existing.display_name) = lower(split.member_name)
  );

PRAGMA user_version = 2;
