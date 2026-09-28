-- Browsing changes popularity, not the project's content update time.
BEGIN IMMEDIATE;
DROP TRIGGER IF EXISTS projects_set_updated_at;
CREATE TRIGGER projects_set_updated_at
AFTER UPDATE OF name, leader, members, category, year, icon, description, media,
  cas_creativity, cas_activity, cas_service, updates, asset_dir ON projects
WHEN NEW.updated_at = OLD.updated_at BEGIN
  UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
PRAGMA user_version = 18;
COMMIT;
