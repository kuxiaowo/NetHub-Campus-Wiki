BEGIN;

-- 只处理仍在使用公开初始密码的旧管理员；已自行改密的同名账号不会受影响。
UPDATE users
SET role = 'user', is_active = 0, updated_at = CURRENT_TIMESTAMP
WHERE username = 'kuxiaowo'
  AND role = 'admin'
  AND password_hash = 'pbkdf2_sha256$260000$sFsreGUvs4sl9blJnDz7-A$pmlfVc0l5Y6jtu13kNneITspjRGRZKeQiZAc7g8gASw';

PRAGMA user_version = 9;

COMMIT;
