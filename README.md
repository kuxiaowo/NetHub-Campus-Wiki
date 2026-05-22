# Campus Wiki 校园论坛 + CAS 项目库

这是一个前后端分离的校园项目展示原型，包含首页公告、CAS 项目库、项目筛选、资源中心、活动照片和项目详情。

## 技术栈

- 前端服务：静态 HTML + CSS + JavaScript，运行在 `frontend_server.py`
- 后端服务：FastAPI + Uvicorn，运行在 `backend/main.py`
- 数据库：MySQL 8+
- 接口文档：`docs/API.md` 和 FastAPI 自动文档 `/docs`

## 目录结构

```text
Campus Wiki/
├── frontend_server.py     # 前端静态文件服务
├── backend/
│   ├── main.py            # FastAPI 路由和 CORS 配置
│   ├── config.py          # 环境变量配置
│   ├── database.py        # MySQL 连接
│   ├── projects.py        # 项目查询和数据格式化
│   ├── resources.py       # 资源中心和活动照片查询
│   └── schemas.py         # API 响应模型
├── public/
│   ├── index.html         # 首页
│   ├── projects.html      # CAS 项目库
│   ├── resources.html     # 资源中心
│   ├── detail.html        # 项目详情
│   ├── css/styles.css
│   └── js/
│       ├── config.js      # 前端 API 地址配置
│       ├── api.js         # Fetch 封装和通用渲染
│       ├── index.js
│       ├── projects.js
│       ├── resources.js
│       └── detail.js
├── docs/API.md            # 详细接口文档
├── docs/DATABASE.md       # 数据库结构文档
├── sql/schema.sql         # MySQL 建表和示例数据
└── requirements.txt
```

## 本地运行

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，按本机 MySQL 配置修改：

```env
API_PORT=3100
FRONTEND_PORT=3200
CORS_ORIGINS=http://127.0.0.1:3200,http://localhost:3200
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=campus_user
DB_PASSWORD=campus_pass_123
DB_NAME=campus_cas_forum
AUTH_SECRET_KEY=change-this-to-a-long-random-secret
AUTH_TOKEN_EXPIRE_MINUTES=120
```

### 3. 初始化数据库

确保 MySQL 已启动，然后导入示例数据。

Windows PowerShell 不要使用 `Get-Content sql/schema.sql | mysql`，也不要直接用 `<` 重定向；这两种方式容易遇到 PowerShell 语法限制或中文编码问题。推荐进入 MySQL 后用 `source` 导入：

```bash
mysql -u root -p -P 3307 --default-character-set=utf8mb4
```

进入 `mysql>` 后执行：

```sql
source D:/Python/programs/GitHub/NetHub-Campus-Wiki/sql/schema.sql;
```

如果你的 MySQL 使用默认端口 `3306`，可以去掉 `-P 3307` 或改成自己的端口。导入后确认 `.env` 中的 `DB_PORT`、`DB_USER`、`DB_PASSWORD` 和实际 MySQL 配置一致。

### 4. 启动后端 API 服务

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 3100 --reload
```

后端地址：

- API 健康检查：http://127.0.0.1:3100/api/health
- 自动接口文档：http://127.0.0.1:3100/docs

### 5. 启动前端服务

另开一个终端：

```bash
python frontend_server.py
```

前端地址：

- 首页：http://127.0.0.1:3200/
- CAS 项目库：http://127.0.0.1:3200/projects.html

如果后端端口变化，修改 `public/js/config.js` 中的 `apiBaseUrl`。

## 数据库结构

当前 `sql/schema.sql` 会重建并写入示例数据，包含 5 张业务表：

- `users`：用户账号。密码使用 PBKDF2-HMAC-SHA256 哈希保存，`role` 使用 `admin` / `user` 区分管理员和普通用户。
- `projects`：CAS 项目。`icon` 保存项目图标图片 URL，`media` 和 `updates` 使用 MySQL JSON 字段保存链接数组和动态数组。
- `resources`：资源中心普通资源卡片。`category` 当前包括 `yearbook`、`photos`、`other`；资源中心不再使用 icon 字段，只使用 `image` 作为封面图。
- `photo_activities`：活动照片分组。`description` 是必填活动简介，用于“全部活动”卡片展示和关键词搜索；活动卡片不再使用 icon 字段。
- `photo_items`：单张活动照片。通过 `activity_id` 关联 `photo_activities.id`，删除活动时照片记录会级联删除。

用户系统提供开放注册、登录和当前用户接口。注册账号默认是普通用户；如果需要初始化管理员，可以先通过页面或 `POST /api/auth/register` 注册账号，再执行：

```sql
UPDATE users SET role = 'admin' WHERE username = '你的用户名';
```

活动照片整包下载后续应由后端提供 ZIP 下载接口，例如 `GET /api/photo-activities/{activity_id}/download`；前端不逐张触发下载。

## 代码规范

- 后端只负责 API、数据访问和响应模型，不再托管前端页面。
- 前端只负责页面渲染和用户交互，通过 `public/js/api.js` 调用后端。
- 环境差异通过 `.env` 和 `public/js/config.js` 配置，不把数据库账号写死到业务代码中。
- API 响应统一使用 JSON；项目列表和详情都返回 `{ "data": ... }`。
- 需要登录的接口使用 `Authorization: Bearer <accessToken>`；前端会把登录 token 保存在浏览器本地存储中。
- 数据库访问集中在 `backend/database.py`、`backend/auth.py`、`backend/projects.py` 和 `backend/resources.py`，路由层不直接拼装业务数据。
- CSS 使用稳定尺寸和明确布局，导航位于网站名右侧，移动端自动换行。
- 更详细的团队代码规范见 [docs/CODE_STYLE.md](docs/CODE_STYLE.md)。

## 接口文档

详细接口见 [docs/API.md](docs/API.md)。运行后端后，也可以访问 FastAPI 自动生成的 OpenAPI 文档：

```text
http://127.0.0.1:3100/docs
```

数据库表结构、字段含义、示例值和表关系见 [docs/DATABASE.md](docs/DATABASE.md)。

## 管理后台

后台入口：

```text
http://127.0.0.1:3200/admin.html
```

后台只允许 `role = admin` 的用户访问。可以先注册普通用户，再在 MySQL 中执行：

```sql
UPDATE users SET role = 'admin' WHERE username = '你的用户名';
```

管理员登录后可以：

- 查看、创建和编辑用户，并调整 `admin/user` 角色。
- 在文件管理栏目浏览 `public/` 目录，并选择目标文件夹上传文件。
- 新建、编辑和删除资源中心资源；后台资源管理直接采用前台资源中心的筛选条、左侧分类和右侧内容布局。
- 在资源管理中选择“活动照片”分类后，会显示左侧活动筛选、右侧活动卡片和活动照片平铺页；进入某个活动后，可在活动标题/描述区域编辑活动。
- 普通资源和活动照片都只手动填写 URL，或浏览 `public/` 选择已有文件/文件夹；活动照片通过 `photoDir` 绑定到 `public/` 下的文件夹，后台不再单张编辑照片。
- 通过受控数据库查看器查看和编辑白名单表。

默认上传文件可以保存到：

```text
public/uploads/
```

也可以在后台文件管理中选择 `public/` 下其他子目录作为上传目标。资源地址可以引用具体文件 URL，也可以引用目录 URL，例如 `/uploads/activity-2026/`。

如果是在已有数据库上升级后台活动照片目录功能，需要执行：

```sql
source D:/Python/programs/GitHub/NetHub-Campus-Wiki/sql/add_photo_dir.sql;
```

后端上传接口依赖 `python-multipart`，安装依赖时请执行：

```bash
pip install -r requirements.txt
```
