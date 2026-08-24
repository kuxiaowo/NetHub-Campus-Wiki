-- Store contact details on the project membership itself. A person can choose
-- different public contact details for different CAS projects.

BEGIN;

ALTER TABLE project_members ADD COLUMN contact_type TEXT
  CHECK (contact_type IS NULL OR contact_type IN ('wechat', 'phone', 'email', 'other'));
ALTER TABLE project_members ADD COLUMN contact_value TEXT;

PRAGMA user_version = 5;
COMMIT;
