-- Resource types now select fixed code paths and are defined in
-- backend/resource_types.py. Remove the former user-configurable metadata table.

BEGIN;

DROP TRIGGER IF EXISTS resource_categories_set_updated_at;
DROP TABLE IF EXISTS resource_categories;

PRAGMA user_version = 4;
COMMIT;
