-- MySQL 8+ 示例数据库脚本
-- 运行方式：mysql -u root -p < sql/schema.sql

CREATE DATABASE IF NOT EXISTS campus_cas_forum
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE campus_cas_forum;

DROP TABLE IF EXISTS projects;

CREATE TABLE projects (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '项目 ID',
  name VARCHAR(120) NOT NULL COMMENT '项目名称',
  leader VARCHAR(80) NOT NULL COMMENT '负责人',
  members TEXT NOT NULL COMMENT '项目成员，可用逗号分隔或 JSON 字符串',
  category VARCHAR(60) NOT NULL COMMENT '分类，例如 科技创新/公益服务/艺术设计',
  year INT NOT NULL COMMENT '项目年份',
  icon VARCHAR(255) DEFAULT NULL COMMENT '项目图标链接或 emoji',
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

INSERT INTO projects
(name, leader, members, category, year, icon, description, media, cas_creativity, cas_activity, cas_service, popularity, updates)
VALUES
(
  '校园噪音地图',
  '李明',
  '李明, 王小雨, Chen Alex',
  '科技创新',
  2026,
  '📡',
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
  '📚',
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
  '🏃',
  '组织午间轻量跑步活动，提供不同速度小组和打卡机制，鼓励同学养成稳定运动习惯。',
  JSON_ARRAY('https://picsum.photos/seed/running-club/900/520'),
  0, 1, 0,
  74,
  JSON_ARRAY('每周三、周五 12:30 集合', '新增 3km 新手路线')
);
