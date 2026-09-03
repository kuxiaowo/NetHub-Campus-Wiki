BEGIN;

ALTER TABLE projects ADD COLUMN asset_dir TEXT;

PRAGMA user_version = 8;

COMMIT;
