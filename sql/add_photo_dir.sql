USE campus_cas_forum;

ALTER TABLE photo_activities
  ADD COLUMN photo_dir VARCHAR(600) DEFAULT NULL COMMENT '活动照片目录 URL，指向 public 下的文件夹'
  AFTER hot;
