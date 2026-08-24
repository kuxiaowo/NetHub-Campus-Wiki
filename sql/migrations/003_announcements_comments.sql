BEGIN IMMEDIATE;

CREATE TABLE announcements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'published' CHECK (status IN ('draft', 'published', 'archived')),
  is_pinned INTEGER NOT NULL DEFAULT 0 CHECK (is_pinned IN (0, 1)),
  view_count INTEGER NOT NULL DEFAULT 0,
  created_by INTEGER,
  published_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX idx_announcements_public
  ON announcements(status, is_pinned DESC, published_at DESC, id DESC);

CREATE TABLE comments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  target_type TEXT NOT NULL CHECK (target_type IN ('announcement', 'project', 'resource')),
  target_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  parent_id INTEGER,
  root_id INTEGER,
  reply_to_user_id INTEGER,
  content TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'visible' CHECK (status IN ('visible', 'deleted', 'hidden')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (parent_id) REFERENCES comments(id) ON DELETE CASCADE,
  FOREIGN KEY (root_id) REFERENCES comments(id) ON DELETE CASCADE,
  FOREIGN KEY (reply_to_user_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX idx_comments_target_roots
  ON comments(target_type, target_id, parent_id, created_at DESC, id DESC);
CREATE INDEX idx_comments_root
  ON comments(root_id, created_at ASC, id ASC);
CREATE INDEX idx_comments_user ON comments(user_id, created_at DESC);

CREATE TABLE comment_likes (
  comment_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (comment_id, user_id),
  FOREIGN KEY (comment_id) REFERENCES comments(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX idx_comment_likes_user ON comment_likes(user_id, created_at DESC);

CREATE TABLE comment_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  comment_id INTEGER NOT NULL,
  reporter_id INTEGER NOT NULL,
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'resolved', 'dismissed')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  resolved_at TEXT,
  resolved_by INTEGER,
  FOREIGN KEY (comment_id) REFERENCES comments(id) ON DELETE CASCADE,
  FOREIGN KEY (reporter_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (resolved_by) REFERENCES users(id) ON DELETE SET NULL,
  UNIQUE (comment_id, reporter_id)
);
CREATE INDEX idx_comment_reports_status ON comment_reports(status, created_at ASC, id ASC);

CREATE TRIGGER announcements_set_updated_at AFTER UPDATE ON announcements
WHEN NEW.updated_at = OLD.updated_at BEGIN
  UPDATE announcements SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
CREATE TRIGGER comments_set_updated_at AFTER UPDATE ON comments
WHEN NEW.updated_at = OLD.updated_at BEGIN
  UPDATE comments SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

INSERT INTO announcements
  (title, summary, content, status, is_pinned, created_by, published_at)
VALUES
(
  'CAS 项目库原型上线',
  '欢迎提交你的项目资料，让更多同学发现正在发生的校园创意与行动。',
  'CAS 项目库现已开放浏览。你可以查看项目简介、成员、动态和相关资源。后续我们还会继续完善项目提交、成员关联和校园互动功能。欢迎通过管理员提交你的项目资料。',
  'published', 1, 1, datetime('now', '-2 days')
),
(
  '本周五举办 CAS 项目分享会',
  '本周五 16:00 举办 CAS 项目分享会，欢迎正在筹备或已经开展项目的同学参加。',
  '分享会将在本周五 16:00 举行。现场将介绍优秀项目案例、CAS 记录方法和团队协作经验，也会预留自由交流时间。具体地点请留意后续更新。',
  'published', 0, 1, datetime('now', '-1 day')
),
(
  '项目展示页支持媒体与动态更新',
  '项目详情现已支持照片、视频链接和阶段性动态。',
  '项目负责人可以通过管理后台维护项目照片、视频链接和阶段性进展。成员信息也会逐步与注册账号关联，方便同学进一步了解项目并发起校园交流。',
  'published', 0, 1, CURRENT_TIMESTAMP
);

PRAGMA user_version = 3;
COMMIT;
