BEGIN IMMEDIATE;

ALTER TABLE photo_activities ADD COLUMN cover_image TEXT;

-- 旧版后台不允许 Yearbook 自定义封面；清空自动保存的第一页缩略图，
-- 让它们继续动态跟随目录中的第一张图片。
UPDATE resources
SET image = ''
WHERE category = 'yearbook';

PRAGMA user_version = 13;
COMMIT;
