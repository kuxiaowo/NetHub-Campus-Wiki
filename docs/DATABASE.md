# 数据库文档

本文档只说明 MySQL 数据库结构、字段含义、示例值和表关系，不描述 HTTP API。接口请求和响应见 `docs/API.md`。

## 基本信息

- 数据库名：`campus_cas_forum`
- 数据库版本：MySQL 8+
- 默认字符集：`utf8mb4`
- 默认排序规则：`utf8mb4_unicode_ci`
- 建表脚本：`sql/schema.sql`

Windows PowerShell 不建议用 `Get-Content sql/schema.sql | mysql` 导入，容易造成中文乱码。推荐进入 MySQL 后执行：

```sql
source D:/Python/programs/GitHub/NetHub-Campus-Wiki/sql/schema.sql;
```

## 表关系概览

```text
projects

resources

photo_activities 1 ──── n photo_items

users
```

- `projects` 独立保存 CAS 项目库数据。
- `resources` 独立保存资源中心普通资源卡片。
- `photo_activities` 保存活动照片分组。
- `photo_items` 保存活动下的单张照片，通过 `activity_id` 关联 `photo_activities.id`。
- `users` 保存登录账号、密码哈希、角色和启用状态。

## `users`

用户账号表。用于注册、登录、当前用户信息和角色区分。

### 字段

| 字段 | 类型 | 约束 | 示例值 | 作用 |
| --- | --- | --- | --- | --- |
| `id` | `INT` | 主键，自增 | `1` | 用户唯一 ID |
| `username` | `VARCHAR(32)` | 非空，唯一 | `student01` | 登录用户名 |
| `password_hash` | `VARCHAR(255)` | 非空 | `pbkdf2_sha256$...` | PBKDF2-HMAC-SHA256 密码哈希 |
| `display_name` | `VARCHAR(80)` | 可空 | `学生 01` | 页面展示名称 |
| `role` | `ENUM('admin','user')` | 非空，默认 `user`，索引 | `user` | 用户角色 |
| `is_active` | `TINYINT(1)` | 非空，默认 `1`，索引 | `1` | 账号是否启用 |
| `created_at` | `TIMESTAMP` | 非空，默认当前时间 | `2026-05-21 12:00:00` | 创建时间 |
| `updated_at` | `TIMESTAMP` | 非空，自动更新 | `2026-05-21 12:00:00` | 更新时间 |

### 角色

| `role` | 展示文案 | 说明 |
| --- | --- | --- |
| `admin` | 管理员 | 管理员账号，后续可用于后台权限控制 |
| `user` | 普通用户 | 默认注册角色 |

注册接口创建的账号固定为 `user`。初始化管理员账号可以先注册一个普通用户，再在 MySQL 中执行：

```sql
UPDATE users SET role = 'admin' WHERE username = '你的用户名';
```

### 索引

| 索引 | 字段 | 作用 |
| --- | --- | --- |
| `PRIMARY` | `id` | 主键查询 |
| `uq_users_username` | `username` | 保证用户名唯一 |
| `idx_users_role` | `role` | 按角色筛选 |
| `idx_users_active` | `is_active` | 按启用状态筛选 |

## `projects`

CAS 项目库表。用于项目库列表、首页推荐项目和项目详情页。

### 字段

| 字段 | 类型 | 约束 | 示例值 | 作用 |
| --- | --- | --- | --- | --- |
| `id` | `INT` | 主键，自增 | `1` | 项目唯一 ID |
| `name` | `VARCHAR(120)` | 非空 | `校园噪音地图` | 项目名称 |
| `leader` | `VARCHAR(80)` | 非空 | `李明` | 项目负责人 |
| `members` | `TEXT` | 非空 | `李明, 王小雨, Chen Alex` | 项目成员描述 |
| `category` | `VARCHAR(60)` | 非空，索引 | `科技创新` | 项目分类，用于筛选 |
| `year` | `INT` | 非空，索引 | `2026` | 项目年份，用于筛选 |
| `icon` | `VARCHAR(255)` | 可空 | `https://picsum.photos/seed/noise-map-icon/300/300` | 项目图标图片 URL |
| `description` | `TEXT` | 非空 | `使用传感器采集校园不同地点的噪音数据...` | 项目简介 |
| `media` | `JSON` | 可空 | `["https://picsum.photos/seed/noise-map/900/520"]` | 项目图片或视频链接数组 |
| `cas_creativity` | `TINYINT(1)` | 非空，默认 `0` | `1` | 是否包含 CAS Creativity |
| `cas_activity` | `TINYINT(1)` | 非空，默认 `0` | `1` | 是否包含 CAS Activity |
| `cas_service` | `TINYINT(1)` | 非空，默认 `0` | `1` | 是否包含 CAS Service |
| `popularity` | `INT` | 非空，默认 `0`，索引 | `96` | 热度值，用于推荐排序 |
| `updates` | `JSON` | 可空 | `["完成第一版传感器数据模拟器"]` | 项目动态文本数组 |
| `created_at` | `TIMESTAMP` | 非空，默认当前时间 | `2026-05-10 10:00:00` | 创建时间 |
| `updated_at` | `TIMESTAMP` | 非空，自动更新 | `2026-05-10 10:00:00` | 更新时间 |

### 索引

| 索引 | 字段 | 作用 |
| --- | --- | --- |
| `PRIMARY` | `id` | 主键查询 |
| `idx_category` | `category` | 分类筛选 |
| `idx_year` | `year` | 年份筛选 |
| `idx_popularity` | `popularity` | 热度排序 |

### 设计说明

- `icon` 现在是图片 URL，不再存 emoji。
- `media` 是项目正文媒体资源，可以包含多张图或视频链接；数组顺序就是正式详情页展示顺序，管理员只在后台项目详情视图中拖拽排序，拖动结束后自动保存，正式前台详情页只展示。
- `icon` 和 `media` 分开：`icon` 用于卡片/列表头像，`media` 用于详情页媒体区。
- CAS 三项用三个布尔字段保存，后端会组合成前端的 `cas.creativity/activity/service`。

## `project_categories`

CAS 项目库左侧分类表。用于控制项目分类是否启用和展示顺序，不控制项目本身排序。

| 字段 | 类型 | 约束 | 示例值 | 作用 |
| --- | --- | --- | --- | --- |
| `id` | `INT` | 主键，自增 | `1` | 分类记录 ID |
| `name` | `VARCHAR(60)` | 非空，唯一 | `科技创新` | 分类名称，对应 `projects.category` |
| `sort_order` | `INT` | 非空，默认 `0`，索引 | `10` | 人工排序权重，数字越小越靠前 |
| `is_active` | `TINYINT(1)` | 非空，默认 `1`，索引 | `1` | 是否在项目库显示 |
| `created_at` | `TIMESTAMP` | 非空，默认当前时间 | `2026-05-10 10:00:00` | 创建时间 |
| `updated_at` | `TIMESTAMP` | 非空，自动更新 | `2026-05-10 10:00:00` | 更新时间 |

默认分类顺序为 `科技创新 = 10`、`公益服务 = 20`、`运动健康 = 30`。现有数据库升级可执行 `sql/add_project_category_sorting.sql`。

## `resources`

资源中心普通资源表。用于资源中心中的 Yearbook、活动照片入口、其他资料卡片。

### 字段

| 字段 | 类型 | 约束 | 示例值 | 作用 |
| --- | --- | --- | --- | --- |
| `id` | `INT` | 主键，自增 | `1` | 资源唯一 ID |
| `title` | `VARCHAR(160)` | 非空 | `2026 校园 Yearbook` | 资源标题 |
| `description` | `TEXT` | 非空 | `收录年度班级合影、活动纪实...` | 资源简介 |
| `year` | `INT` | 非空，索引 | `2026` | 资源年份 |
| `category` | `VARCHAR(40)` | 非空，索引 | `yearbook` | 资源分类值，给程序筛选使用 |
| `label` | `VARCHAR(60)` | 非空 | `Yearbook` | 资源分类展示名 |
| `type` | `VARCHAR(40)` | 非空 | `年鉴` | 资源类型展示名 |
| `hot` | `INT` | 非空，默认 `0`，索引 | `96` | 热度，用于排序 |
| `downloads` | `INT` | 非空，默认 `0`，索引 | `820` | 下载次数，用于排序 |
| `image` | `VARCHAR(600)` | 非空 | `https://images.unsplash.com/...` | 资源封面图片 URL |
| `resource_url` | `VARCHAR(600)` | 非空 | `https://images.unsplash.com/...` | 资源访问或下载 URL |
| `created_at` | `TIMESTAMP` | 非空，默认当前时间 | `2026-05-10 10:00:00` | 创建时间 |
| `updated_at` | `TIMESTAMP` | 非空，自动更新 | `2026-05-10 10:00:00` | 更新时间 |

### 当前分类值

| `category` | `label` | 说明 |
| --- | --- | --- |
| `yearbook` | `Yearbook` | 年鉴资源 |
| `photos` | `活动照片` | 活动照片入口 |
| `other` | `其他资源` | 文档或其他资料 |

### 索引

| 索引 | 字段 | 作用 |
| --- | --- | --- |
| `PRIMARY` | `id` | 主键查询 |
| `idx_resource_category` | `category` | 分类筛选 |
| `idx_resource_year` | `year` | 年份筛选 |
| `idx_resource_hot` | `hot` | 热度排序 |
| `idx_resource_downloads` | `downloads` | 下载量排序 |

### 设计说明

- 资源中心不使用 icon 字段。
- 卡片视觉只使用 `image` 作为封面图。
- `category` 是稳定程序值，`label` 是展示文字。
- 普通资源卡片不使用人工排序，仍按接口的 `hot`、`new`、`old`、`download` 规则排序。

## `resource_categories`

资源中心左侧分类表。用于控制资源分类展示名称、是否启用和人工排序。

| 字段 | 类型 | 约束 | 示例值 | 作用 |
| --- | --- | --- | --- | --- |
| `id` | `INT` | 主键，自增 | `1` | 分类记录 ID |
| `value` | `VARCHAR(40)` | 非空，唯一 | `other` | 分类程序值，对应 `resources.category` |
| `label` | `VARCHAR(60)` | 非空 | `其他资源` | 分类展示名称 |
| `sort_order` | `INT` | 非空，默认 `0`，索引 | `999` | 人工排序权重，数字越小越靠前 |
| `is_active` | `TINYINT(1)` | 非空，默认 `1`，索引 | `1` | 是否在资源中心显示 |
| `created_at` | `TIMESTAMP` | 非空，默认当前时间 | `2026-05-10 10:00:00` | 创建时间 |
| `updated_at` | `TIMESTAMP` | 非空，自动更新 | `2026-05-10 10:00:00` | 更新时间 |

默认分类顺序为 `yearbook = 10`、`photos = 20`、`other = 999`，所以“其他资源”默认显示在左侧分类底部。

## `photo_activities`

活动照片分组表。每条记录代表一个活动，例如“春季运动会”。

### 字段

| 字段 | 类型 | 约束 | 示例值 | 作用 |
| --- | --- | --- | --- | --- |
| `id` | `INT` | 主键，自增 | `1` | 活动唯一 ID |
| `activity` | `VARCHAR(160)` | 非空 | `春季运动会` | 活动名称 |
| `description` | `TEXT` | 非空 | `记录开幕式、接力赛、领奖瞬间...` | 活动简介，用于全部活动卡片和搜索 |
| `year` | `INT` | 非空，索引 | `2026` | 活动年份 |
| `hot` | `INT` | 非空，默认 `0`，索引 | `98` | 活动热度 |
| `sort_order` | `INT` | 非空，默认 `0`，索引 | `10` | 活动列表人工排序权重，数字越小越靠前 |
| `photo_dir` | `VARCHAR(600)` | 可空 | `/uploads/sports-2026/` | 活动照片目录 URL，指向 `public/` 下的文件夹 |
| `created_at` | `TIMESTAMP` | 非空，默认当前时间 | `2026-05-10 10:00:00` | 创建时间 |
| `updated_at` | `TIMESTAMP` | 非空，自动更新 | `2026-05-10 10:00:00` | 更新时间 |

### 索引

| 索引 | 字段 | 作用 |
| --- | --- | --- |
| `PRIMARY` | `id` | 主键查询 |
| `idx_photo_activity_year` | `year` | 年份筛选 |
| `idx_photo_activity_hot` | `hot` | 热度排序 |
| `idx_photo_activity_sort` | `sort_order, id` | 活动列表人工排序 |

### 设计说明

- 活动卡片不使用 icon 字段。
- “全部活动”视图使用活动下第一张照片作为封面。
- `sort_order` 只控制活动列表和“全部活动”中活动卡片的活动顺序，不控制单张照片排序。
- `description` 是必填字段，当前开发阶段不做旧表兼容。
- 活动照片 v1 推荐使用 `photo_dir` 目录模型：一个活动对应 `public/` 下的一个文件夹。
- 公开活动照片接口会扫描 `photo_dir` 下的图片文件生成照片列表；未配置目录时兼容旧 `photo_items` 数据。
- 现有数据库升级照片目录可执行 `sql/add_photo_dir.sql`；升级资源分类和活动列表排序可执行 `sql/add_resource_category_activity_sorting.sql`。

## `photo_items`

单张活动照片表。每条记录代表某个活动下的一张照片。

### 字段

| 字段 | 类型 | 约束 | 示例值 | 作用 |
| --- | --- | --- | --- | --- |
| `id` | `INT` | 主键，自增 | `1` | 照片唯一 ID |
| `activity_id` | `INT` | 非空，外键 | `1` | 所属活动 ID |
| `title` | `VARCHAR(160)` | 非空 | `开幕式` | 照片标题，当前不在缩略图下展示，但用于 `alt` 和弹窗标题 |
| `image_url` | `VARCHAR(600)` | 非空 | `https://images.unsplash.com/...` | 照片访问 URL |
| `sort_order` | `INT` | 非空，默认 `0` | `1` | 活动内照片排序 |
| `created_at` | `TIMESTAMP` | 非空，默认当前时间 | `2026-05-10 10:00:00` | 创建时间 |

### 外键

```sql
FOREIGN KEY (activity_id) REFERENCES photo_activities(id)
ON DELETE CASCADE
```

作用：

- 每张照片必须属于一个活动。
- 删除活动时，该活动下的照片记录会自动删除。

### 索引

| 索引 | 字段 | 作用 |
| --- | --- | --- |
| `PRIMARY` | `id` | 主键查询 |
| `idx_photo_items_activity` | `activity_id, sort_order` | 按活动取照片并排序 |

### 设计说明

- 数据库存照片 URL，不存图片二进制。
- 当前示例使用远程图片 URL。
- 后续本地挂载方案建议使用相对路径，例如 `/uploads/photos/sports-2026/opening.jpg`。
- 照片标题虽然不在缩略图下展示，但仍然有用：弹窗标题、图片 `alt`、文件下载名都可以使用它。

## 活动照片下载设计

当前前端只保留“下载压缩文件”入口，不再逐张触发下载。

活动压缩文件不单独写入数据库，由 `photo_dir` 自动推导：如果 `photo_dir` 是 `/uploads/photos/春季运动会/`，压缩文件应放在 `public/uploads/photos/春季运动会/春季运动会.rar`。只有同名 `.rar` 文件实际存在时，接口才返回 `archiveUrl`。

## 字段命名约定

- 数据库字段使用 `snake_case`。
- 前端接口字段使用 `camelCase`。
- 后端数据访问层负责转换，例如：

```text
created_at -> createdAt
updated_at -> updatedAt
resource_url -> resourceUrl
sort_order -> sortOrder
image_url -> src
photo_dir -> photoDir
```

`archiveUrl` 是由 `photo_dir` 推导出来的接口字段，不对应数据库字段。

## 当前不做的设计

- 不把图片二进制存入 MySQL。
- 不在资源中心或活动照片表中保存 icon 字段。
- 不做旧数据库结构兼容；开发阶段以 `sql/schema.sql` 为准。
- 不在前端逐张下载整个活动照片；活动整包下载使用照片目录下的同名压缩文件。

## 管理后台数据约定

管理后台新增 `project_categories` 管理 CAS 项目库左侧分类顺序，新增 `resource_categories` 管理资源中心左侧分类顺序，继续使用 `projects`、`resources`、`photo_activities`、`photo_items` 管理项目、资源和活动照片。上传文件不写入 MySQL 二进制字段，只保存 URL。

### 上传文件

- 上传目录：`public/uploads/`
- 数据库存储：资源封面写入 `resources.image`，资源文件或目录 URL 写入 `resources.resource_url`，活动照片目录写入 `photo_activities.photo_dir`。
- 上传过程不写入数据库；后台“文件管理”直接读取 `public/` 目录，资源管理中的普通资源和活动照片都只保存 URL 引用。
- 普通文件名由后端生成随机安全文件名；`.rar` 压缩文件保留原文件名，用于活动照片目录同名下载。
- 允许类型：`jpg`、`jpeg`、`png`、`webp`、`gif`、`pdf`、`doc`、`docx`、`ppt`、`pptx`、`xls`、`xlsx`、`zip`、`rar`。

### 数据库查看器

数据库查看器是受控 CRUD，不开放任意 SQL。可访问表白名单：

- `users`
- `projects`
- `project_categories`
- `resource_categories`
- `resources`
- `photo_activities`
- `photo_items`

字段限制：

- `users.password_hash` 不返回、不允许编辑。
- `users` 表新增记录必须通过用户管理接口创建，数据库查看器不直接创建用户。
- `id`、`created_at`、`updated_at` 是只读字段。
- 表名必须来自白名单，字段名必须来自 `INFORMATION_SCHEMA.COLUMNS`。
- 删除 `photo_activities` 会通过外键级联删除对应 `photo_items`。
