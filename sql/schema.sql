-- SQLite 初始化脚本。后端首次连接空数据库时自动执行。
PRAGMA foreign_keys = ON;

CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  display_name TEXT,
  role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_users_role ON users(role);
CREATE INDEX idx_users_active ON users(is_active);

CREATE TABLE projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  leader TEXT NOT NULL,
  members TEXT NOT NULL,
  category TEXT NOT NULL,
  year INTEGER NOT NULL,
  icon TEXT,
  description TEXT NOT NULL,
  media TEXT,
  cas_creativity INTEGER NOT NULL DEFAULT 0 CHECK (cas_creativity IN (0, 1)),
  cas_activity INTEGER NOT NULL DEFAULT 0 CHECK (cas_activity IN (0, 1)),
  cas_service INTEGER NOT NULL DEFAULT 0 CHECK (cas_service IN (0, 1)),
  popularity INTEGER NOT NULL DEFAULT 0,
  updates TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_projects_category ON projects(category);
CREATE INDEX idx_projects_year ON projects(year);
CREATE INDEX idx_projects_popularity ON projects(popularity);

CREATE TABLE project_categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  sort_order INTEGER NOT NULL DEFAULT 0,
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_project_categories_sort ON project_categories(is_active, sort_order, id);

CREATE TABLE resources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  description TEXT,
  year INTEGER NOT NULL,
  category TEXT NOT NULL,
  label TEXT NOT NULL,
  hot INTEGER NOT NULL DEFAULT 0,
  downloads INTEGER NOT NULL DEFAULT 0,
  image TEXT NOT NULL,
  resource_url TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_resources_category ON resources(category);
CREATE INDEX idx_resources_year ON resources(year);
CREATE INDEX idx_resources_hot ON resources(hot);
CREATE INDEX idx_resources_downloads ON resources(downloads);

CREATE TABLE photo_activities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  activity TEXT NOT NULL,
  description TEXT NOT NULL,
  year INTEGER NOT NULL,
  hot INTEGER NOT NULL DEFAULT 0,
  downloads INTEGER NOT NULL DEFAULT 0,
  sort_order INTEGER NOT NULL DEFAULT 0,
  photo_dir TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_photo_activities_year ON photo_activities(year);
CREATE INDEX idx_photo_activities_hot ON photo_activities(hot);
CREATE INDEX idx_photo_activities_downloads ON photo_activities(downloads);
CREATE INDEX idx_photo_activities_sort ON photo_activities(sort_order, id);

CREATE TABLE photo_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  activity_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  image_url TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (activity_id) REFERENCES photo_activities(id) ON DELETE CASCADE
);
CREATE INDEX idx_photo_items_activity ON photo_items(activity_id, sort_order);

-- 保留原数据库自动更新时间的行为。
CREATE TRIGGER users_set_updated_at AFTER UPDATE ON users
WHEN NEW.updated_at = OLD.updated_at BEGIN
  UPDATE users SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
CREATE TRIGGER projects_set_updated_at AFTER UPDATE ON projects
WHEN NEW.updated_at = OLD.updated_at BEGIN
  UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
CREATE TRIGGER project_categories_set_updated_at AFTER UPDATE ON project_categories
WHEN NEW.updated_at = OLD.updated_at BEGIN
  UPDATE project_categories SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
CREATE TRIGGER resources_set_updated_at AFTER UPDATE ON resources
WHEN NEW.updated_at = OLD.updated_at BEGIN
  UPDATE resources SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
CREATE TRIGGER photo_activities_set_updated_at AFTER UPDATE ON photo_activities
WHEN NEW.updated_at = OLD.updated_at BEGIN
  UPDATE photo_activities SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

-- 新数据库只创建结构。业务数据和首个管理员均由部署者显式录入。
PRAGMA user_version = 1;
