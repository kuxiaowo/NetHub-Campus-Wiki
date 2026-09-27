-- Apply with an authenticated Cloudflare D1 migration command before baseline.
-- The runtime HMAC gateway intentionally rejects DDL.
CREATE TABLE IF NOT EXISTS _sync_events (
    seq INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    payload_hash TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS _sync_watermark (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    seq INTEGER NOT NULL
);
INSERT OR IGNORE INTO _sync_watermark (id, seq) VALUES (1, 0);
