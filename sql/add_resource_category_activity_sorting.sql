-- Upgrade existing databases for resource category and activity list sorting.
-- Run inside the campus_cas_forum database.

CREATE TABLE IF NOT EXISTS resource_categories (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '资源分类 ID',
  value VARCHAR(40) NOT NULL COMMENT '资源分类值，例如 yearbook/photos/other',
  label VARCHAR(60) NOT NULL COMMENT '资源分类展示名称',
  sort_order INT NOT NULL DEFAULT 0 COMMENT '人工排序权重，数字越小越靠前',
  is_active TINYINT(1) NOT NULL DEFAULT 1 COMMENT '分类是否启用',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_resource_categories_value (value),
  INDEX idx_resource_categories_sort (is_active, sort_order, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO resource_categories (value, label, sort_order, is_active)
VALUES
('yearbook', 'Yearbook', 10, 1),
('photos', '活动照片', 20, 1),
('other', '其他资源', 999, 1)
ON DUPLICATE KEY UPDATE
  label = VALUES(label),
  sort_order = VALUES(sort_order),
  is_active = VALUES(is_active);

INSERT INTO resource_categories (value, label, sort_order, is_active)
SELECT r.category, MIN(r.label), 500, 1
FROM resources r
LEFT JOIN resource_categories rc ON rc.value = r.category
WHERE rc.id IS NULL
GROUP BY r.category;

SET @photo_sort_column_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'photo_activities'
    AND COLUMN_NAME = 'sort_order'
);
SET @photo_sort_column_sql := IF(
  @photo_sort_column_exists = 0,
  'ALTER TABLE photo_activities ADD COLUMN sort_order INT NOT NULL DEFAULT 0 COMMENT ''人工排序权重，数字越小越靠前''',
  'SELECT 1'
);
PREPARE photo_sort_column_stmt FROM @photo_sort_column_sql;
EXECUTE photo_sort_column_stmt;
DEALLOCATE PREPARE photo_sort_column_stmt;

UPDATE photo_activities
SET sort_order = id * 10
WHERE sort_order = 0;

SET @photo_sort_index_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'photo_activities'
    AND INDEX_NAME = 'idx_photo_activity_sort'
);
SET @photo_sort_index_sql := IF(
  @photo_sort_index_exists = 0,
  'CREATE INDEX idx_photo_activity_sort ON photo_activities (sort_order, id)',
  'SELECT 1'
);
PREPARE photo_sort_index_stmt FROM @photo_sort_index_sql;
EXECUTE photo_sort_index_stmt;
DEALLOCATE PREPARE photo_sort_index_stmt;

INSERT INTO users (username, password_hash, display_name, role, is_active)
VALUES
(
  'kuxiaowo',
  'pbkdf2_sha256$260000$a3V4aWFvd28tYWRtaW4tMDE$TdAF_ZJWEz0cqhL2I8sJo1_dxjYbOkGwNTNKdv-1PXM',
  '庞正心',
  'admin',
  1
)
ON DUPLICATE KEY UPDATE
  display_name = VALUES(display_name),
  role = VALUES(role),
  is_active = VALUES(is_active);
