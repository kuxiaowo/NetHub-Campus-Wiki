# 数据库文档

项目使用 SQLite。数据库是一个本地文件，不需要单独安装、启动或维护数据库
服务；Python 后端使用标准库 `sqlite3` 访问。

## 配置与初始化

数据库路径由 `.env` 中的 `DATABASE_PATH` 控制：

```env
DATABASE_PATH=data/campus_wiki.db
```

相对路径以项目根目录为基准，也可以配置绝对路径。后端首次连接一个空数据库时，
自动执行 `sql/schema.sql`，创建表、索引、外键、触发器、示例数据和默认管理员。
脚本最后设置 `PRAGMA user_version = 1`，后端以此判断数据库是否已经初始化。

运行参数：

- `foreign_keys = ON`：启用外键与级联删除。
- `journal_mode = WAL`：提升并发读写体验。
- `busy_timeout = 5000`：数据库短暂占用时最多等待 5 秒。
- `recursive_triggers = OFF`：更新时间触发器不递归执行。

数据库查看器和在线“修复表结构”接口已经删除。后续结构变更应采用版本化迁移
脚本，并递增 `user_version`，不要让运行中的网站任意修改表结构。

## 表关系

```text
users

projects
project_categories

resources
resource_categories

photo_activities 1 ──── n photo_items
```

## 表说明

### `users`

保存登录账号、PBKDF2 密码哈希、角色和启用状态。

- `username` 唯一。
- `role` 只能为 `admin` 或 `user`。
- `is_active` 只能为 `0` 或 `1`。
- 新注册账号固定为普通用户；管理员通过后台用户管理调整角色。

### `projects`

保存 CAS 项目。`media` 和 `updates` 使用 JSON 字符串存储数组，数据访问层负责
将其转换为接口中的数组。`cas_creativity`、`cas_activity`、`cas_service` 使用
`0/1` 表示布尔值。

### `project_categories`

保存 CAS 项目分类及人工排序权重。`name` 唯一，`sort_order` 越小越靠前。

### `resources`

保存普通资源和 Yearbook。活动照片不写入该表。`resource_url` 保存资源文件或
Yearbook 目录 URL，`image` 保存封面 URL。

### `resource_categories`

保存资源中心分类入口。`value` 唯一，默认包含 `yearbook`、`photos` 和 `other`。

### `photo_activities`

保存活动照片分组、热度、下载量、排序以及可选的 `photo_dir`。配置目录时，后端
优先扫描 `public/` 下的实际图片；未配置时兼容 `photo_items` 中的记录。

### `photo_items`

保存活动下的单张照片记录，通过 `activity_id` 外键关联 `photo_activities.id`。
删除活动时，其照片记录会级联删除。

## 字段与接口命名

数据库字段使用 `snake_case`，API 使用 `camelCase`，由后端数据访问层转换：

```text
created_at   -> createdAt
updated_at   -> updatedAt
resource_url -> resourceUrl
sort_order   -> sortOrder
image_url    -> src
photo_dir    -> photoDir
```

数据库只保存文件 URL 或目录 URL，不保存图片、PDF 或压缩包二进制。

## 备份与重建

备份时先停止后端，再复制 `DATABASE_PATH` 指向的 `.db` 文件。WAL 模式运行期间
可能同时存在 `-wal` 和 `-shm` 文件，因此不要在服务持续写入时只复制主文件。

需要重建开发数据时：

1. 停止后端。
2. 备份或删除 `.db`、`.db-wal`、`.db-shm`。
3. 重新启动后端，由 `sql/schema.sql` 自动初始化。

生产环境的数据迁移不应通过删除数据库完成。
