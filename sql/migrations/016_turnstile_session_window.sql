ALTER TABLE auth_sessions ADD COLUMN turnstile_verified_at INTEGER;

PRAGMA user_version = 16;
