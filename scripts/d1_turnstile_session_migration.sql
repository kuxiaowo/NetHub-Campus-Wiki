-- Apply with an authenticated Cloudflare D1 migration command before deploying
-- the application change. The runtime HMAC gateway rejects DDL by design.
ALTER TABLE auth_sessions ADD COLUMN turnstile_verified_at INTEGER;
