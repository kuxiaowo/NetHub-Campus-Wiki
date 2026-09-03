BEGIN IMMEDIATE;

CREATE TABLE auth_security_settings (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  login_ip_limit INTEGER NOT NULL DEFAULT 10 CHECK (login_ip_limit >= 1),
  admin_login_ip_limit INTEGER NOT NULL DEFAULT 5 CHECK (admin_login_ip_limit >= 1),
  login_failure_limit INTEGER NOT NULL DEFAULT 5 CHECK (login_failure_limit >= 1),
  login_failure_cooldown_minutes INTEGER NOT NULL DEFAULT 10
    CHECK (login_failure_cooldown_minutes >= 1),
  register_hourly_limit INTEGER NOT NULL DEFAULT 3 CHECK (register_hourly_limit >= 1),
  register_daily_limit INTEGER NOT NULL DEFAULT 10 CHECK (register_daily_limit >= 1),
  password_change_hourly_limit INTEGER NOT NULL DEFAULT 5
    CHECK (password_change_hourly_limit >= 1),
  updated_by INTEGER,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (updated_by) REFERENCES users(id) ON DELETE SET NULL
);

INSERT INTO auth_security_settings (id) VALUES (1);

CREATE TABLE auth_rate_limit_buckets (
  bucket_key TEXT PRIMARY KEY,
  window_started_at INTEGER NOT NULL,
  attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  updated_at INTEGER NOT NULL
);
CREATE INDEX idx_auth_rate_limit_updated
  ON auth_rate_limit_buckets(updated_at);

PRAGMA user_version = 11;
COMMIT;
