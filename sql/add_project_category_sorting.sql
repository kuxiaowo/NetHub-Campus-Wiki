-- Upgrade existing databases for CAS project category sorting.
-- Run inside the campus_cas_forum database.

CREATE TABLE IF NOT EXISTS project_categories (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'CAS 项目分类 ID',
  name VARCHAR(60) NOT NULL COMMENT 'CAS 项目分类名称',
  sort_order INT NOT NULL DEFAULT 0 COMMENT '人工排序权重，数字越小越靠前',
  is_active TINYINT(1) NOT NULL DEFAULT 1 COMMENT '分类是否启用',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_project_categories_name (name),
  INDEX idx_project_categories_sort (is_active, sort_order, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO project_categories (name, sort_order, is_active)
VALUES
('科技创新', 10, 1),
('公益服务', 20, 1),
('运动健康', 30, 1)
ON DUPLICATE KEY UPDATE
  sort_order = VALUES(sort_order),
  is_active = VALUES(is_active);

INSERT INTO project_categories (name, sort_order, is_active)
SELECT p.category, 500, 1
FROM projects p
LEFT JOIN project_categories pc ON pc.name = p.category
WHERE pc.id IS NULL
GROUP BY p.category;
