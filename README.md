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
├── sql/schema.sql         # MySQL 初始化脚本、示例数据和默认管理员
└── requirements.txt
```

## 本地运行

### 1. 安装依赖

```bash
python3 -m pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，按本机 MySQL 和部署地址修改：

```env
API_PORT=3100
FRONTEND_PORT=3200
FRONTEND_API_BASE_URL=http://127.0.0.1:3100/api
CORS_ORIGINS=http://127.0.0.1:3200,http://localhost:3200
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=campus_user
DB_PASSWORD=campus_pass_123
DB_NAME=campus_cas_forum
AUTH_SECRET_KEY=change-this-to-a-long-random-secret
AUTH_TOKEN_EXPIRE_MINUTES=120
PHOTO_DIR_CACHE_MINUTES=5
```

`FRONTEND_API_BASE_URL` 是浏览器实际请求的后端 API 前缀，必须包含 `/api`，例如 `https://api.example.com/api`。使用 `frontend_server.py` 启动前端时，`/js/config.js` 会从 `.env` 动态生成；如果不填写，默认使用 `http://127.0.0.1:${API_PORT}/api`。

`CORS_ORIGINS` 是允许访问后端的前端页面来源，只写协议、域名和端口，不带路径，例如 `https://wiki.example.com`。前后端分离部署时，需要同时修改：

- 前端请求后端：`FRONTEND_API_BASE_URL=https://后端域名/api`
- 后端允许前端跨域：`CORS_ORIGINS=https://前端域名`

### 3. 初始化数据库

确保 MySQL 已启动，然后在项目根目录导入示例数据：

```bash
mysql -u root -p --default-character-set=utf8mb4 < sql/schema.sql
```

也可以先进入 MySQL，再使用 Linux 绝对路径导入：

```bash
mysql -u root -p --default-character-set=utf8mb4
```

进入 `mysql>` 后执行：

```sql
source /opt/campus-wiki/sql/schema.sql;
```

如果你的 MySQL 不使用默认端口 `3306`，在 `mysql` 命令中追加 `-P 你的端口`。

`schema.sql` 会创建网站里的默认管理员账号，但不会创建 MySQL 数据库登录账号。后端连接 MySQL 使用的是 `.env` 里的 `DB_USER` 和 `DB_PASSWORD`，需要使用已有 MySQL 账号，或自行创建并授权：

```sql
CREATE USER 'campus_user'@'localhost' IDENTIFIED BY 'campus_pass_123';
GRANT ALL PRIVILEGES ON campus_cas_forum.* TO 'campus_user'@'localhost';
FLUSH PRIVILEGES;
```

然后确认 `.env` 中的 `DB_PORT`、`DB_USER`、`DB_PASSWORD` 和实际 MySQL 配置一致。如果直接使用 `root` 连接，也可以把 `.env` 改成 root 账号和密码。

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
python3 frontend_server.py
```

前端地址：

- 首页：http://127.0.0.1:3200/
- CAS 项目库：http://127.0.0.1:3200/projects.html

如果后端端口或域名变化，修改 `.env` 中的 `FRONTEND_API_BASE_URL`，然后重启前端服务。后端的 `CORS_ORIGINS` 也要包含当前前端页面的来源，否则浏览器会拦截跨域请求。

## 数据库结构

当前只保留一个数据库初始化脚本：`sql/schema.sql`。该脚本会重建数据库结构、写入示例数据，并创建默认管理员。初始化后包含这些表：

- `users`：用户账号。密码使用 PBKDF2-HMAC-SHA256 哈希保存，`role` 使用 `admin` / `user` 区分管理员和普通用户。
- `projects`：CAS 项目。`icon` 保存项目图标图片 URL，`media` 和 `updates` 使用 MySQL JSON 字段保存链接数组和动态数组。
- `project_categories`：CAS 项目库左侧分类。`sortOrder` 是人工排序权重，数字越小越靠前；分类排序不影响项目本身排序。
- `resource_categories`：资源中心左侧分类。`sortOrder` 是人工排序权重，数字越小越靠前；默认 `other` 排在最下面。
- `resources`：资源中心普通资源卡片。`category` 当前包括 `yearbook`、`other`；活动照片不写入该表，统一来自 `photo_activities`。资源中心不再使用 icon 字段，只使用 `image` 作为封面图。
- `photo_activities`：活动照片分组。`description` 是必填活动简介，用于“全部活动”卡片展示和关键词搜索；活动卡片不再使用 icon 字段；`sortOrder` 控制左侧活动列表顺序；`downloads` 统计整场活动的照片下载次数。
- `photo_items`：单张活动照片。通过 `activity_id` 关联 `photo_activities.id`，删除活动时照片记录会级联删除。

用户系统提供开放注册、登录和当前用户接口。注册账号默认是普通用户；默认管理员由 `sql/schema.sql` 初始化创建。

资源中心采用“查看公开、下载需登录”的权限模型：未登录用户可以浏览资源列表、查看活动照片、打开照片放大预览和阅读 Yearbook 图片页面；点击普通资源文件、Yearbook PDF、活动照片压缩包或单张照片下载时必须登录。前端未登录点击下载会弹出 `抱歉，需要登陆` 并阻止下载。

活动照片整包下载使用照片目录下的同名压缩文件。比如 `photoDir` 为 `/uploads/photos/春季运动会/` 时，请把压缩文件放在 `/uploads/photos/春季运动会/春季运动会.rar`，接口会通过 `archiveUrl` 返回下载地址。活动照片下载量是活动级统计，点击整包下载或在放大弹窗里下载单张照片都会增加 `photo_activities.downloads`。

Yearbook 资源使用 `resources.resource_url` 指向 `public/` 下的一个目录，例如 `/uploads/yearbook/2026/`。目录内放所有页面图片和 PDF 文件；页面图片支持 `.jpg`、`.jpeg`、`.png`、`.webp`、`.gif`。封面不单独维护，自动使用目录内文件名自然升序的第一张图片。前台进入 Yearbook 后会按文件名自然升序展示图片页面，每次显示两页并按两页翻页。PDF 下载按钮使用目录内文件名自然升序的第一个 `.pdf`，建议命名为 `yearbook.pdf`。页面图片建议使用 `001.png`、`002.png`、`003.png` 这类带前导零的文件名，避免排序歧义。

资源统计会由前台行为自动维护：打开 Yearbook 阅读器或进入某个活动照片详情会增加热度；热度使用通用节流逻辑，同一登录账户对同一对象 5 秒内只会增加一次。已登录用户点击普通资源链接、Yearbook PDF、Yearbook 单页图片、活动照片整包或活动单张照片下载会增加下载数，下载数不节流；未登录用户会被前端提示登录，不会增加下载数；后台预览和后台下载不计入统计。

活动照片前台接口分为活动列表和单活动照片列表：`/api/photo-activities` 只返回活动摘要、封面和照片数量，进入某个活动后再请求 `/api/photo-activities/{activity_id}/photos` 获取照片。照片目录扫描使用后端进程内缓存，`PHOTO_DIR_CACHE_MINUTES` 控制缓存有效期，单位是分钟。默认 5 分钟内每个活动目录复用同一份照片列表，不重复扫描目录；缓存过期后的下一次访问会重新扫描目录并为新增照片生成缩略图。设置为 `0` 可关闭缓存，方便开发调试。

## 代码规范

- 后端只负责 API、数据访问和响应模型，不再托管前端页面。
- 前端只负责页面渲染和用户交互，通过 `public/js/api.js` 调用后端。
- 环境差异通过 `.env` 配置；前端运行时的 `/js/config.js` 由 `frontend_server.py` 根据 `.env` 生成，不把数据库账号或后端地址写死到业务代码中。
- API 响应统一使用 JSON；项目列表和详情都返回 `{ "data": ... }`。
- 需要登录的接口使用 `Authorization: Bearer <accessToken>`；前端会把登录 token 保存在浏览器本地存储中。浏览器原生下载链接不能附加请求头时，前端会把本地 `public/` 文件 URL 转成 `/api/files/...?...token=...` 形式的受保护下载地址。
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

示例数据内置管理员账号：

```text
用户名：kuxiaowo
展示名：庞正心
密码：123geufo
```

该账号用于本地示例和初始化验证，生产环境请修改密码或删除。

后台只允许 `role = admin` 的用户访问。默认管理员由初始化脚本创建；如果需要把其他用户提升为管理员，可以在 MySQL 中执行：

```sql
UPDATE users SET role = 'admin' WHERE username = '你的用户名';
```

管理员登录后可以：

- 查看、创建和编辑用户，并调整 `admin/user` 角色。
- 在文件管理栏目浏览 `public/` 目录，并选择目标文件夹上传文件。
- 新建和编辑 CAS 项目；项目行点击进入后台内部详情视图，详情视图提供编辑按钮和 `media` 拖拽排序，媒体拖动结束后自动保存；正式前台详情页只负责展示。拖拽 CAS 项目库左侧分类调整分类顺序，分类顺序会同步影响前台项目库。
- 新建、编辑和删除资源中心资源；后台资源管理直接采用前台资源中心的筛选条、左侧分类和右侧内容布局。
- 拖拽资源中心左侧分类调整分类顺序，拖拽“活动照片”分类下的左侧活动列表调整活动顺序。
- 在资源管理中选择“活动照片”分类后，会显示左侧活动筛选、右侧活动卡片和活动照片平铺页；进入某个活动后，可在活动标题/描述区域编辑活动。
- 普通资源和活动照片都只手动填写 URL，或浏览 `public/` 选择已有文件/文件夹；活动照片通过 `photoDir` 绑定到 `public/` 下的文件夹，后台不再单张编辑照片。
- 通过受控数据库查看器查看和编辑白名单表。

默认上传文件可以保存到：

```text
public/uploads/
```

也可以在后台文件管理中选择 `public/` 下其他子目录作为上传目标。资源地址可以引用具体文件 URL，也可以引用目录 URL，例如 `/uploads/activity-2026/`。

前端静态服务会直接放行图片文件，保证照片和 Yearbook 页面可以匿名查看；会拒绝直接访问 `.pdf`、`.zip`、`.rar`、`.7z`、Office 文档等下载型文件。下载这类文件应走后端 `/api/files/{file_path}`，由登录状态校验后作为附件返回。

初始化和重建数据库统一执行 `sql/schema.sql`。已运行的旧数据库如果缺少 `photo_activities.downloads`，后端会在活动照片相关接口前自动补列并创建下载量索引；生产环境仍建议先备份并手动执行同等 SQL 补丁。

`sortOrder` 表示人工排序权重，数字越小越靠前。后台拖拽会自动维护为 `10, 20, 30...`；当前用于 CAS 项目分类、资源分类和活动列表，不用于普通项目、普通资源卡片或单张照片卡片。

后端上传接口依赖 `python-multipart`，安装依赖时请执行：

```bash
python3 -m pip install -r requirements.txt
```
