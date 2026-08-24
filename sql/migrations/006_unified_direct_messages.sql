-- Remove the per-member message-request state. All visible conversations now
-- share one inbox; unsolicited senders are controlled by a dynamic daily limit.

BEGIN IMMEDIATE;

DROP INDEX idx_conversation_members_user;

CREATE TABLE conversation_members_v6 (
  conversation_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  last_read_message_id INTEGER,
  hidden_at TEXT,
  muted INTEGER NOT NULL DEFAULT 0 CHECK (muted IN (0, 1)),
  joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (conversation_id, user_id),
  FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

INSERT INTO conversation_members_v6
  (conversation_id, user_id, last_read_message_id, hidden_at, muted, joined_at)
SELECT conversation_id, user_id, last_read_message_id, hidden_at, muted, joined_at
FROM conversation_members;

DROP TABLE conversation_members;
ALTER TABLE conversation_members_v6 RENAME TO conversation_members;

CREATE INDEX idx_conversation_members_user
  ON conversation_members(user_id, hidden_at, conversation_id);

PRAGMA user_version = 6;
COMMIT;
