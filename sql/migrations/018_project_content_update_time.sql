-- Browsing changes popularity, not the project's content update time.
BEGIN IMMEDIATE;
DROP TRIGGER IF EXISTS projects_set_updated_at;
CREATE TRIGGER projects_set_updated_at
AFTER UPDATE OF name, leader, members, category, year, icon, description, media,
  cas_creativity, cas_activity, cas_service, updates, asset_dir ON projects
WHEN NEW.updated_at = OLD.updated_at AND (
  NEW.name IS NOT OLD.name OR NEW.leader IS NOT OLD.leader OR
  NEW.members IS NOT OLD.members OR NEW.category IS NOT OLD.category OR
  NEW.year IS NOT OLD.year OR NEW.icon IS NOT OLD.icon OR
  NEW.description IS NOT OLD.description OR NEW.media IS NOT OLD.media OR
  NEW.cas_creativity IS NOT OLD.cas_creativity OR
  NEW.cas_activity IS NOT OLD.cas_activity OR
  NEW.cas_service IS NOT OLD.cas_service OR NEW.updates IS NOT OLD.updates OR
  NEW.asset_dir IS NOT OLD.asset_dir
) BEGIN
  UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
PRAGMA user_version = 18;
COMMIT;
