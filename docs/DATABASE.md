# 数据库文档

项目使用 SQLite。数据库是一个本地文件，不需要单独安装、启动或维护数据库
服务；Python 后端使用标准库 `sqlite3` 访问。

## 配置与初始化

数据库路径由 `.env` 中的 `DATABASE_PATH` 控制：

```env
DATABASE_PATH=data/campus_wiki.db
```

相对路径以项目根目录为基准，也可以配置绝对路径。后端首次连接一个空数据库时，
自动执行 `sql/schema.sql`，只创建表、索引、外键和触发器，不插入业务数据或用户账号。
脚本最后设置 `PRAGMA user_version = 1`，后端以此判断数据库是否已经初始化。

首次部署通过 `python -m backend.bootstrap_admin --username <昵称>` 交互式创建首个管理员。该命令在已有启用中的管理员时会拒绝执行，密码也不会作为命令行参数传递。

运行参数：

- `foreign_keys = ON`：启用外键与级联删除。
- `journal_mode = WAL`：提升并发读写体验。
- `busy_timeout`：由 `.env` 的 `DATABASE_BUSY_TIMEOUT_MS` 控制，默认 5000 毫秒。
- 连接等待时间：由 `.env` 的 `DATABASE_CONNECT_TIMEOUT_SECONDS` 控制，默认 5 秒。
- `recursive_triggers = OFF`：更新时间触发器不递归执行。

数据库查看器和在线“修复表结构”接口已经删除。后续结构变更应采用版本化迁移
脚本，并递增 `user_version`，不要让运行中的网站任意修改表结构。

## 表关系

```text
users

projects
project_categories

resources

photo_activities 1 ──── n photo_items

announcements ─┐
projects ──────┼── comments 1 ──── n comments (reply)
resources ─────┘       │
                       ├──── n comment_likes
                       ├──── n comment_reports
                       └──── n comment_notifications
```

## 表说明

### `users`

保存登录账号、PBKDF2 密码哈希、角色和启用状态。

- `username` 唯一。
- `role` 只能为 `admin` 或 `user`。
- `is_active` 只能为 `0` 或 `1`。
- `deleted_at` 非空表示账号已匿名化注销；该行继续保留，以维持历史留言和私信外键。
- 新注册账号固定为普通用户；管理员通过后台用户管理调整角色。

### `auth_security_settings` / `auth_rate_limit_buckets`

`auth_security_settings` 是单行动态配置表，保存注册、普通登录、管理员登录、用户名连续失败冷却和修改密码的限额，并记录最后修改人和时间。管理员后台保存后，后续请求立即读取新值。

`auth_rate_limit_buckets` 保存经过 SHA-256 摘要处理的 IP、用户名或用户 ID 限流桶，不直接保存这些标识的原文。固定窗口和连续登录失败记录均写入该表，因此服务重启后计数不会清空；超过保留时间的普通限流桶会在后续认证请求中清理。

### `projects`

保存 CAS 项目。`asset_dir` 保存 `/CAS/` 下的项目资源目录。`updates` 使用 JSON
字符串存储结构化动态数组，每项包含稳定 `id`、`content` 和属于该动态的相对
图片路径 `images` 数组；公共数据访问层会把相对路径解析为完整 URL。新发布的动态还保存
`authorPersonId`、`authorName`、`authorRole` 和 `createdAt`。动态作者关联项目成员档案，而不是站内用户；
后台可选择当前项目的任意成员代发，无需先绑定账号。站内成员自行发布时，后端仍通过
`project_members -> people.user_id` 校验其操作权限。删除动态时会同时从该 JSON 数组移除记录，并删除
`asset_dir/updates/<动态ID>/` 中的专属上传文件。旧动态中的 `authorUserId` 仅用于兼容读取和权限判断。
`media` 是旧版项目级媒体字段，仅保留用于接口结构兼容，新后台不再写入，前台也不展示。
`cas_creativity`、`cas_activity`、`cas_service` 使用
`0/1` 表示布尔值。`leader` 和 `members` 是供旧接口及列表展示使用的摘要字段；
项目刚创建、尚未在详情页维护成员时，两者允许为空字符串。成员的规范数据以
`project_members` 为准，负责人也只能由其中 `role = 'leader'` 的记录确定。

### `project_categories`

保存 CAS 项目分类及人工排序权重。`name` 唯一，`sort_order` 越小越靠前。

### `resources`

保存普通资源、Yearbook 和“老师驾到”视频。活动照片不写入该表。`resource_url`
保存资源文件、Yearbook 目录或浏览器可直接播放的视频 URL；“老师驾到”的
`image` 保存选填的自定义封面 URL，留空时接口会尝试使用本地视频首帧；其他普通资源
使用 `image` 保存封面 URL。

资源类型不是数据库内容。`yearbook`、`photos`、`teacher` 和 `other` 固定定义在
`backend/resource_types.py`，分别选择 Yearbook、活动照片、老师视频和普通资源处理逻辑。

### `photo_activities`

保存活动照片分组、热度、下载量、排序以及可选的 `photo_dir`。配置目录时，后端
优先扫描 `public/` 下的实际图片；未配置时兼容 `photo_items` 中的记录。

### `photo_items`

保存活动下的单张照片记录，通过 `activity_id` 外键关联 `photo_activities.id`。
删除活动时，其照片记录会级联删除。

### `announcements`

保存公告标题、摘要、正文、发布/归档状态、置顶状态和浏览量。归档可重新发布；永久删除公告时，业务层会同步清理关联留言及通知。

### `comments`

公告、项目和资源共用的多态留言表。`target_type + target_id` 标识留言对象；因为对象来自三张表，数据库不为 `target_id` 建单一外键，由后端在写入前验证目标存在。`parent_id` 记录直接回复对象，`root_id` 记录所属主留言，因此界面固定展示为两级，同时仍能表达“回复某条回复”。

`status` 为 `visible`、`deleted` 或 `hidden`。用户删除使用 `deleted` 并清空正文，以保留回复树；管理员处理举报可设为 `hidden`。

### `comment_likes` / `comment_reports`

`comment_likes` 使用 `(comment_id, user_id)` 联合主键防止重复点赞。`comment_reports` 对同一用户和留言保持一条记录，管理员可处理或忽略，并记录处理人和处理时间。

### `comment_notifications`

保存直接回复和留言点赞产生的永久通知。通知冗余保存目标类型和目标 ID，且不对 `comment_id` 设置级联外键，因此留言删除、隐藏或原内容不存在后仍可显示失效记录。`read_at` 保存分类已读状态；同一用户取消后重新点赞时复用原通知并重新标为未读。迁移 007 不回填升级前的互动。

## 字段与接口命名

数据库字段使用 `snake_case`，API 使用 `camelCase`，由后端数据访问层转换：

```text
created_at   -> createdAt
updated_at   -> updatedAt
resource_url -> resourceUrl
asset_dir    -> assetDir
sort_order   -> sortOrder
image_url    -> src
photo_dir    -> photoDir
```

数据库只保存文件 URL、目录 URL 或相对于 CAS 项目目录的路径，不保存图片、PDF 或压缩包二进制。

## JSON 数据迁移

管理后台的 JSON 导入/导出是业务数据迁移层，不是 SQLite 物理备份。它包含 CAS
项目、结构化成员及项目内联系方式、动态、普通资源、活动照片、统计值、人工顺序和
资源路径；不包含数据库 ID、账号绑定、创建/更新时间，也不包含实际资源文件。

每次导入都会创建新的业务记录和待确认人员档案，不按姓名或标题合并。一个导入批次
使用同一个数据库事务：任意字段验证失败时不会写入；站内路径不存在或文件/目录类型
不符时只产生预警，管理员明确确认后仍可整批导入。需要完整灾难恢复时仍应按下文备份
SQLite 数据库及对应的 `public/` 资源目录。

## 备份与重建

备份时先停止后端，再复制 `DATABASE_PATH` 指向的 `.db` 文件。WAL 模式运行期间
可能同时存在 `-wal` 和 `-shm` 文件，因此不要在服务持续写入时只复制主文件。

需要重建开发数据时：

1. 停止后端。
2. 备份或删除 `.db`、`.db-wal`、`.db-shm`。
3. 重新启动后端，由 `sql/schema.sql` 自动初始化。

生产环境的数据迁移不应通过删除数据库完成。

## 用户、人员与私信表

账号和现实人员采用分离模型：

- `users`：登录账号、公开资料、校园关联状态和私信权限。
- `people`：已经被 CAS 项目收录的现实人员，`user_id` 可为空。
- `project_members`：项目与人员的多对多关系，保存负责人/成员角色、历史展示名、排序以及该成员在当前项目中的联系方式。`contact_type` 可为 `wechat`、`phone`、`email`、`other` 或空，`contact_value` 保存对应内容；联系方式不放在 `people` 中，避免一个人在不同项目中的公开方式相互覆盖。
- `person_claims`：旧版用户认领流程的历史记录表；当前不再开放新增或审核接口，仅为兼容已有数据库保留。
- `user_follows`、`user_blocks`：用户关系和黑名单。
- `conversations`：两名用户之间唯一的一对一会话。
- `conversation_members`：每个参与者的已读、隐藏和免打扰状态。
- `messages`：文本或项目卡片消息，撤回采用 `recalled_at` 软删除。
- `message_reports`：消息举报审核记录。

不要通过姓名自动把 `people` 绑定到 `users`。旧文本数据迁移会为每个项目创建独立人员档案，之后只能由管理员在对应 CAS 项目详情的成员区域选择账号完成绑定。

数据库结构通过 `sql/migrations` 目录中的连续编号脚本升级。每个脚本必须在事务中执行并更新 `PRAGMA user_version`；后端检测到版本缺口时会拒绝启动，避免跳版本造成半套结构。当前最新版本为 12：002 增加用户关系、人员认领和私信，003 增加公告与通用留言，004 移除旧资源分类表，005 为项目成员关系增加联系方式，006 取消消息请求状态并统一私信会话，007 增加回复与点赞通知，008 增加 CAS 项目资源目录并迁移旧图标和动态图片路径，009 降权并禁用仍保留公开初始密码哈希的旧默认管理员，010 增加用户注销标记并把公告状态收敛为发布/归档，011 增加认证访问限制的动态配置和持久化计数，012 将中英文并列的 CAS 成员姓名统一为英文名在前。
