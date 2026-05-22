-- MySQL 8+ 示例数据库脚本
-- Windows PowerShell 推荐进入 mysql 后执行：
-- source D:/Python/programs/GitHub/NetHub-Campus-Wiki/sql/schema.sql;

CREATE DATABASE IF NOT EXISTS campus_cas_forum
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE campus_cas_forum;

DROP TABLE IF EXISTS photo_items;
DROP TABLE IF EXISTS photo_activities;
DROP TABLE IF EXISTS resources;
DROP TABLE IF EXISTS projects;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '用户 ID',
  username VARCHAR(32) NOT NULL COMMENT '登录用户名',
  password_hash VARCHAR(255) NOT NULL COMMENT 'PBKDF2 密码哈希',
  display_name VARCHAR(80) DEFAULT NULL COMMENT '展示名称',
  role ENUM('admin', 'user') NOT NULL DEFAULT 'user' COMMENT '用户角色：admin 管理员，user 普通用户',
  is_active TINYINT(1) NOT NULL DEFAULT 1 COMMENT '账号是否启用',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_users_username (username),
  INDEX idx_users_role (role),
  INDEX idx_users_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE projects (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '项目 ID',
  name VARCHAR(120) NOT NULL COMMENT '项目名称',
  leader VARCHAR(80) NOT NULL COMMENT '负责人',
  members TEXT NOT NULL COMMENT '项目成员，可用逗号分隔或 JSON 字符串',
  category VARCHAR(60) NOT NULL COMMENT '分类，例如 科技创新/公益服务/艺术设计',
  year INT NOT NULL COMMENT '项目年份',
  icon VARCHAR(255) DEFAULT NULL COMMENT '项目图标图片 URL',
  description TEXT NOT NULL COMMENT '简要介绍/完整简介',
  media JSON DEFAULT NULL COMMENT '照片/视频链接数组，JSON 格式',
  cas_creativity TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否包含 Creativity',
  cas_activity TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否包含 Activity',
  cas_service TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否包含 Service',
  popularity INT NOT NULL DEFAULT 0 COMMENT '热度，用于推荐排序',
  updates JSON DEFAULT NULL COMMENT '项目动态数组，JSON 格式',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_category (category),
  INDEX idx_year (year),
  INDEX idx_popularity (popularity)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE resources (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '资源 ID',
  title VARCHAR(160) NOT NULL COMMENT '资源标题',
  description TEXT NOT NULL COMMENT '资源简介',
  year INT NOT NULL COMMENT '资源年份',
  category VARCHAR(40) NOT NULL COMMENT '资源分类值，例如 yearbook/photos/other',
  label VARCHAR(60) NOT NULL COMMENT '资源分类展示名',
  type VARCHAR(40) NOT NULL COMMENT '资源类型展示名',
  hot INT NOT NULL DEFAULT 0 COMMENT '热度',
  downloads INT NOT NULL DEFAULT 0 COMMENT '下载次数',
  image VARCHAR(600) NOT NULL COMMENT '封面图片 URL',
  resource_url VARCHAR(600) NOT NULL COMMENT '资源访问或下载 URL',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_resource_category (category),
  INDEX idx_resource_year (year),
  INDEX idx_resource_hot (hot),
  INDEX idx_resource_downloads (downloads)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE photo_activities (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '活动 ID',
  activity VARCHAR(160) NOT NULL COMMENT '活动名称',
  description TEXT NOT NULL COMMENT '活动照片简介',
  year INT NOT NULL COMMENT '活动年份',
  hot INT NOT NULL DEFAULT 0 COMMENT '活动热度',
  photo_dir VARCHAR(600) DEFAULT NULL COMMENT '活动照片目录 URL，指向 public 下的文件夹',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_photo_activity_year (year),
  INDEX idx_photo_activity_hot (hot)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE photo_items (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '照片 ID',
  activity_id INT NOT NULL COMMENT '所属活动 ID',
  title VARCHAR(160) NOT NULL COMMENT '照片标题',
  image_url VARCHAR(600) NOT NULL COMMENT '照片 URL',
  sort_order INT NOT NULL DEFAULT 0 COMMENT '活动内排序',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_photo_items_activity
    FOREIGN KEY (activity_id) REFERENCES photo_activities(id)
    ON DELETE CASCADE,
  INDEX idx_photo_items_activity (activity_id, sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO projects
(name, leader, members, category, year, icon, description, media, cas_creativity, cas_activity, cas_service, popularity, updates)
VALUES
(
  '校园噪音地图',
  '李明',
  '李明, 王小雨, Chen Alex',
  '科技创新',
  2026,
  'https://picsum.photos/seed/noise-map-icon/300/300',
  '使用传感器采集校园不同地点的噪音数据，并在网页地图上进行可视化，帮助同学寻找安静学习区域。项目包含硬件采集、后端接口、前端热力图展示与数据分析。',
  JSON_ARRAY('https://picsum.photos/seed/noise-map/900/520', 'https://example.com/videos/noise-map-demo.mp4'),
  1, 1, 1,
  96,
  JSON_ARRAY('完成第一版传感器数据模拟器', '新增热力图展示页面', '计划接入真实 ESP32 设备')
),
(
  '旧书循环计划',
  '张宁',
  '张宁, 刘悦, Sam Wong',
  '公益服务',
  2025,
  'https://picsum.photos/seed/book-cycle-icon/300/300',
  '建立校园旧书登记、捐赠与交换机制，让毕业生和低年级同学更方便地共享教材与课外书。项目重视社区参与、线下活动组织和持续服务。',
  JSON_ARRAY('https://picsum.photos/seed/book-cycle/900/520'),
  1, 0, 1,
  88,
  JSON_ARRAY('完成第一轮旧书收集 120 本', '与图书馆志愿者社团建立合作', '准备上线预约领取表单')
),
(
  '午间跑步社群',
  '赵一航',
  '赵一航, Emily Xu',
  '运动健康',
  2026,
  'https://picsum.photos/seed/running-club-icon/300/300',
  '组织午间轻量跑步活动，提供不同速度小组和打卡机制，鼓励同学养成稳定运动习惯。',
  JSON_ARRAY('https://picsum.photos/seed/running-club/900/520'),
  0, 1, 0,
  74,
  JSON_ARRAY('每周三、周五 12:30 集合', '新增 3km 新手路线')
);

INSERT INTO resources
(title, description, year, category, label, type, hot, downloads, image, resource_url)
VALUES
(
  '2026 校园 Yearbook',
  '收录年度班级合影、活动纪实、社团风采和校园大事记。',
  2026,
  'yearbook',
  'Yearbook',
  '年鉴',
  96,
  820,
  'https://images.unsplash.com/photo-1523050854058-8df90110c9f1?auto=format&fit=crop&w=900&q=80',
  'https://images.unsplash.com/photo-1523050854058-8df90110c9f1?auto=format&fit=crop&w=1600&q=90'
),
(
  '春季运动会照片集',
  '开幕式、接力赛、领奖瞬间等活动照片，支持按活动继续查看。',
  2026,
  'photos',
  '活动照片',
  '照片',
  91,
  642,
  'https://images.unsplash.com/photo-1461896836934-ffe607ba8211?auto=format&fit=crop&w=900&q=80',
  'https://images.unsplash.com/photo-1461896836934-ffe607ba8211?auto=format&fit=crop&w=1600&q=90'
),
(
  '校园文化节影像资源',
  '舞台演出、社团展位和合影留念等精选照片资源。',
  2026,
  'photos',
  '活动照片',
  '照片',
  88,
  591,
  'https://images.unsplash.com/photo-1501281668745-f7f57925c3b4?auto=format&fit=crop&w=900&q=80',
  'https://images.unsplash.com/photo-1501281668745-f7f57925c3b4?auto=format&fit=crop&w=1600&q=90'
),
(
  'CAS 使用指南',
  '统一身份认证、常见问题、账号找回和校内系统访问说明。',
  2026,
  'other',
  '其他资源',
  '文档',
  79,
  734,
  'https://images.unsplash.com/photo-1497366754035-f200968a6e72?auto=format&fit=crop&w=900&q=80',
  'https://images.unsplash.com/photo-1497366754035-f200968a6e72?auto=format&fit=crop&w=1600&q=90'
),
(
  '2025 毕业纪念册',
  '毕业典礼、班级寄语、校园告别和年度人物记录。',
  2025,
  'yearbook',
  'Yearbook',
  '年鉴',
  83,
  506,
  'https://images.unsplash.com/photo-1541339907198-e08756dedf3f?auto=format&fit=crop&w=900&q=80',
  'https://images.unsplash.com/photo-1541339907198-e08756dedf3f?auto=format&fit=crop&w=1600&q=90'
),
(
  '图书馆资源导览',
  '电子图书、学术期刊、研究数据库和馆藏检索教程。',
  2025,
  'other',
  '其他资源',
  '文档',
  70,
  488,
  'https://images.unsplash.com/photo-1521587760476-6c12a4b040da?auto=format&fit=crop&w=900&q=80',
  'https://images.unsplash.com/photo-1521587760476-6c12a4b040da?auto=format&fit=crop&w=1600&q=90'
);

INSERT INTO photo_activities (id, activity, description, year, hot)
VALUES
(1, '春季运动会', '记录开幕式、接力赛、领奖瞬间和操场看台等运动会现场照片。', 2026, 98),
(2, '校园文化节', '收录舞台演出、社团展位、音乐现场和合影留念等文化节影像。', 2026, 92),
(3, '毕业典礼', '整理拨穗仪式、毕业合照和校园告别等毕业季纪念照片。', 2026, 89),
(4, '新生迎新会', '记录签到现场、志愿服务和校园导览等迎新活动片段。', 2025, 76),
(5, '艺术展览', '展示展厅、作品墙和观展交流等艺术展览现场照片。', 2025, 72);

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
