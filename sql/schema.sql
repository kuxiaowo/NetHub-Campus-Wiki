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

CREATE TABLE direct_conversations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_low_id INTEGER NOT NULL,
  user_high_id INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK (user_low_id < user_high_id),
  UNIQUE (user_low_id, user_high_id),
  FOREIGN KEY (user_low_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (user_high_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX idx_direct_conversations_low ON direct_conversations(user_low_id, updated_at DESC);
CREATE INDEX idx_direct_conversations_high ON direct_conversations(user_high_id, updated_at DESC);

CREATE TABLE direct_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id INTEGER NOT NULL,
  sender_id INTEGER NOT NULL,
  content TEXT NOT NULL CHECK (length(trim(content)) BETWEEN 1 AND 2000),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  read_at TEXT,
  FOREIGN KEY (conversation_id) REFERENCES direct_conversations(id) ON DELETE CASCADE,
  FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX idx_direct_messages_conversation ON direct_messages(conversation_id, id DESC);
CREATE INDEX idx_direct_messages_unread ON direct_messages(conversation_id, read_at, sender_id);

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

CREATE TABLE project_members (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  display_name TEXT NOT NULL CHECK (length(trim(display_name)) BETWEEN 1 AND 80),
  role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('leader', 'member')),
  user_id INTEGER,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX idx_project_members_project ON project_members(project_id, sort_order, id);
CREATE UNIQUE INDEX uq_project_members_linked_user
ON project_members(project_id, user_id)
WHERE user_id IS NOT NULL;

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

CREATE TABLE resource_categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  value TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_resource_categories_sort ON resource_categories(is_active, sort_order, id);

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
CREATE TRIGGER project_members_set_updated_at AFTER UPDATE ON project_members
WHEN NEW.updated_at = OLD.updated_at BEGIN
  UPDATE project_members SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
CREATE TRIGGER direct_messages_touch_conversation AFTER INSERT ON direct_messages BEGIN
  UPDATE direct_conversations SET updated_at = NEW.created_at WHERE id = NEW.conversation_id;
END;
CREATE TRIGGER direct_messages_validate_sender BEFORE INSERT ON direct_messages
WHEN NOT EXISTS (
  SELECT 1
  FROM direct_conversations conversation
  WHERE conversation.id = NEW.conversation_id
    AND (conversation.user_low_id = NEW.sender_id OR conversation.user_high_id = NEW.sender_id)
) BEGIN
  SELECT RAISE(ABORT, 'message sender is not a conversation participant');
END;
CREATE TRIGGER project_categories_set_updated_at AFTER UPDATE ON project_categories
WHEN NEW.updated_at = OLD.updated_at BEGIN
  UPDATE project_categories SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
CREATE TRIGGER resources_set_updated_at AFTER UPDATE ON resources
WHEN NEW.updated_at = OLD.updated_at BEGIN
  UPDATE resources SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
CREATE TRIGGER resource_categories_set_updated_at AFTER UPDATE ON resource_categories
WHEN NEW.updated_at = OLD.updated_at BEGIN
  UPDATE resource_categories SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
CREATE TRIGGER photo_activities_set_updated_at AFTER UPDATE ON photo_activities
WHEN NEW.updated_at = OLD.updated_at BEGIN
  UPDATE photo_activities SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

INSERT INTO users (username, password_hash, display_name, role, is_active)
VALUES (
  'kuxiaowo',
  'pbkdf2_sha256$260000$sFsreGUvs4sl9blJnDz7-A$pmlfVc0l5Y6jtu13kNneITspjRGRZKeQiZAc7g8gASw',
  '庞正心',
  'admin',
  1
);

INSERT INTO projects
  (name, leader, members, category, year, icon, description, media,
   cas_creativity, cas_activity, cas_service, popularity, updates)
VALUES
(
  '校园噪音地图', '李明', '李明, 王小雨, Chen Alex', '科技创新', 2026,
  'https://picsum.photos/seed/noise-map-icon/300/300',
  '使用传感器采集校园不同地点的噪音数据，并在网页地图上进行可视化，帮助同学寻找安静学习区域。项目包含硬件采集、后端接口、前端热力图展示与数据分析。',
  '["https://picsum.photos/seed/noise-map/900/520","https://example.com/videos/noise-map-demo.mp4"]',
  1, 1, 1, 96,
  '["完成第一版传感器数据模拟器","新增热力图展示页面","计划接入真实 ESP32 设备"]'
),
(
  '旧书循环计划', '张宁', '张宁, 刘悦, Sam Wong', '公益服务', 2025,
  'https://picsum.photos/seed/book-cycle-icon/300/300',
  '建立校园旧书登记、捐赠与交换机制，让毕业生和低年级同学更方便地共享教材与课外书。项目重视社区参与、线下活动组织和持续服务。',
  '["https://picsum.photos/seed/book-cycle/900/520"]',
  1, 0, 1, 88,
  '["完成第一轮旧书收集 120 本","与图书馆志愿者社团建立合作","准备上线预约领取表单"]'
),
(
  '午间跑步社群', '赵一航', '赵一航, Emily Xu', '运动健康', 2026,
  'https://picsum.photos/seed/running-club-icon/300/300',
  '组织午间轻量跑步活动，提供不同速度小组和打卡机制，鼓励同学养成稳定运动习惯。',
  '["https://picsum.photos/seed/running-club/900/520"]',
  0, 1, 0, 74,
  '["每周三、周五 12:30 集合","新增 3km 新手路线"]'
);

INSERT INTO project_members (project_id, display_name, role, sort_order)
VALUES
  (1, '李明', 'leader', 0),
  (1, '王小雨', 'member', 10),
  (1, 'Chen Alex', 'member', 20),
  (2, '张宁', 'leader', 0),
  (2, '刘悦', 'member', 10),
  (2, 'Sam Wong', 'member', 20),
  (3, '赵一航', 'leader', 0),
  (3, 'Emily Xu', 'member', 10);

INSERT INTO project_categories (name, sort_order, is_active)
VALUES ('科技创新', 10, 1), ('公益服务', 20, 1), ('运动健康', 30, 1);

INSERT INTO resources
  (title, description, year, category, label, hot, downloads, image, resource_url)
VALUES
(
  '2026 校园 Yearbook', '收录年度班级合影、活动纪实、社团风采和校园大事记。',
  2026, 'yearbook', 'Yearbook', 96, 820,
  'https://images.unsplash.com/photo-1523050854058-8df90110c9f1?auto=format&fit=crop&w=900&q=80',
  'https://images.unsplash.com/photo-1523050854058-8df90110c9f1?auto=format&fit=crop&w=1600&q=90'
),
(
  'CAS 使用指南', '统一身份认证、常见问题、账号找回和校内系统访问说明。',
  2026, 'other', '其他资源', 79, 734,
  'https://images.unsplash.com/photo-1497366754035-f200968a6e72?auto=format&fit=crop&w=900&q=80',
  'https://images.unsplash.com/photo-1497366754035-f200968a6e72?auto=format&fit=crop&w=1600&q=90'
),
(
  '2025 毕业纪念册', '毕业典礼、班级寄语、校园告别和年度人物记录。',
  2025, 'yearbook', 'Yearbook', 83, 506,
  'https://images.unsplash.com/photo-1541339907198-e08756dedf3f?auto=format&fit=crop&w=900&q=80',
  'https://images.unsplash.com/photo-1541339907198-e08756dedf3f?auto=format&fit=crop&w=1600&q=90'
),
(
  '图书馆资源导览', '电子图书、学术期刊、研究数据库和馆藏检索教程。',
  2025, 'other', '其他资源', 70, 488,
  'https://images.unsplash.com/photo-1521587760476-6c12a4b040da?auto=format&fit=crop&w=900&q=80',
  'https://images.unsplash.com/photo-1521587760476-6c12a4b040da?auto=format&fit=crop&w=1600&q=90'
);

INSERT INTO resource_categories (value, label, sort_order, is_active)
VALUES ('yearbook', 'Yearbook', 10, 1), ('photos', '活动照片', 20, 1), ('other', '其他资源', 999, 1);

INSERT INTO photo_activities (id, activity, description, year, hot, downloads, sort_order)
VALUES
(1, '春季运动会', '记录开幕式、接力赛、领奖瞬间和操场看台等运动会现场照片。', 2026, 98, 24, 10),
(2, '校园文化节', '收录舞台演出、社团展位、音乐现场和合影留念等文化节影像。', 2026, 92, 18, 20),
(3, '毕业典礼', '整理拨穗仪式、毕业合照和校园告别等毕业季纪念照片。', 2026, 89, 31, 30),
(4, '新生迎新会', '记录签到现场、志愿服务和校园导览等迎新活动片段。', 2025, 76, 12, 40),
(5, '艺术展览', '展示展厅、作品墙和观展交流等艺术展览现场照片。', 2025, 72, 9, 50);

INSERT INTO photo_items (activity_id, title, image_url, sort_order)
VALUES
(1, '开幕式', 'https://images.unsplash.com/photo-1461896836934-ffe607ba8211?auto=format&fit=crop&w=1200&q=85', 1),
(1, '接力赛', 'https://images.unsplash.com/photo-1552674605-db6ffd4facb5?auto=format&fit=crop&w=1200&q=85', 2),
(1, '领奖时刻', 'https://images.unsplash.com/photo-1526676037777-05a232554f77?auto=format&fit=crop&w=1200&q=85', 3),
(1, '操场看台', 'https://images.unsplash.com/photo-1517649763962-0c623066013b?auto=format&fit=crop&w=1200&q=85', 4),
(2, '舞台演出', 'https://images.unsplash.com/photo-1501281668745-f7f57925c3b4?auto=format&fit=crop&w=1200&q=85', 1),
(2, '社团展位', 'https://images.unsplash.com/photo-1515169067865-5387ec356754?auto=format&fit=crop&w=1200&q=85', 2),
(2, '合影留念', 'https://images.unsplash.com/photo-1529156069898-49953e39b3ac?auto=format&fit=crop&w=1200&q=85', 3),
(2, '音乐现场', 'https://images.unsplash.com/photo-1517457373958-b7bdd4587205?auto=format&fit=crop&w=1200&q=85', 4),
(3, '拨穗仪式', 'https://images.unsplash.com/photo-1523050854058-8df90110c9f1?auto=format&fit=crop&w=1200&q=85', 1),
(3, '毕业合照', 'https://images.unsplash.com/photo-1627556704302-624286467c65?auto=format&fit=crop&w=1200&q=85', 2),
(3, '校园告别', 'https://images.unsplash.com/photo-1541339907198-e08756dedf3f?auto=format&fit=crop&w=1200&q=85', 3),
(4, '签到现场', 'https://images.unsplash.com/photo-1523580846011-d3a5bc25702b?auto=format&fit=crop&w=1200&q=85', 1),
(4, '志愿服务', 'https://images.unsplash.com/photo-1521737604893-d14cc237f11d?auto=format&fit=crop&w=1200&q=85', 2),
(4, '校园导览', 'https://images.unsplash.com/photo-1562774053-701939374585?auto=format&fit=crop&w=1200&q=85', 3),
(5, '展厅', 'https://images.unsplash.com/photo-1531058020387-3be344556be6?auto=format&fit=crop&w=1200&q=85', 1),
(5, '作品墙', 'https://images.unsplash.com/photo-1545989253-02cc26577f88?auto=format&fit=crop&w=1200&q=85', 2),
(5, '观展交流', 'https://images.unsplash.com/photo-1518998053901-5348d3961a04?auto=format&fit=crop&w=1200&q=85', 3);

PRAGMA user_version = 2;
