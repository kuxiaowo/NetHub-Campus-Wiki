BEGIN IMMEDIATE;

ALTER TABLE users ADD COLUMN auth_sub TEXT;

CREATE UNIQUE INDEX idx_users_auth_sub
  ON users(auth_sub)
  WHERE auth_sub IS NOT NULL;

CREATE TABLE legacy_local_accounts_archive (
  user_id INTEGER PRIMARY KEY,
  username TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  archived_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

INSERT INTO legacy_local_accounts_archive (user_id, username, password_hash)
SELECT id, username, password_hash
FROM users
WHERE auth_sub IS NULL;

-- Wiki did not have production users before central authentication. Keep old
-- development rows for business foreign keys, but make them impossible to log in
-- and release their usernames for real central members.
UPDATE users
SET username = 'legacy_disabled_' || id || '_' || lower(hex(randomblob(8))),
    password_hash = '',
    role = 'user',
    is_active = 0
WHERE auth_sub IS NULL;

CREATE TABLE auth_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  token_hash TEXT NOT NULL UNIQUE,
  user_id INTEGER NOT NULL,
  auth_sub TEXT,
  sid TEXT,
  created_at INTEGER NOT NULL,
  last_seen_at INTEGER NOT NULL,
  idle_expires_at INTEGER NOT NULL,
  absolute_expires_at INTEGER NOT NULL,
  revoked_at INTEGER,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX idx_auth_sessions_user ON auth_sessions(user_id);
CREATE INDEX idx_auth_sessions_sub ON auth_sessions(auth_sub);
CREATE INDEX idx_auth_sessions_sid ON auth_sessions(sid);

CREATE TABLE oidc_login_attempts (
  state_hash TEXT PRIMARY KEY,
  code_verifier TEXT NOT NULL,
  nonce TEXT NOT NULL,
  return_to TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);

CREATE TABLE backchannel_logout_events (
  jti TEXT PRIMARY KEY,
  received_at INTEGER NOT NULL
);

PRAGMA user_version = 14;
COMMIT;
