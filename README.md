# Campus Wiki 校园论坛 + CAS 项目库

这是一个前后端分离的校园项目展示原型，包含首页公告、CAS 项目库、项目筛选、资源中心、活动照片和项目详情。

## 技术栈

- 前端服务：静态 HTML + CSS + JavaScript，运行在 `frontend_server.py`
- 后端服务：FastAPI + Uvicorn，运行在 `backend/main.py`
- 数据库：SQLite（Python 标准库，无需单独安装数据库服务）
- 接口文档：`docs/API.md` 和 FastAPI 自动文档 `/docs`

## 目录结构

```text
Campus Wiki/
├── frontend_server.py     # 前端静态文件服务
├── backend/
│   ├── main.py            # FastAPI 路由和 CORS 配置
│   ├── config.py          # 环境变量配置
│   ├── database.py        # SQLite 连接与自动初始化
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
│       ├── resource-ui.js # 前后台共用的资源卡片与排序
│       ├── resources.js
│       └── detail.js
├── docs/API.md            # 详细接口文档
├── docs/DATABASE.md       # 数据库结构文档
├── sql/schema.sql         # SQLite 初始化脚本、示例数据和默认管理员
└── requirements.txt
```

## 本地运行

### 1. 安装依赖

```bash
python3 -m pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，按部署地址和数据库文件位置修改：

```env
API_PORT=3100
FRONTEND_PORT=3200
FRONTEND_API_BASE_URL=http://127.0.0.1:3100/api
CORS_ORIGINS=http://127.0.0.1:3200,http://localhost:3200
DATABASE_PATH=data/campus_wiki.db
AUTH_SECRET_KEY=change-this-to-a-long-random-secret
AUTH_TOKEN_EXPIRE_MINUTES=120
PHOTO_DIR_CACHE_MINUTES=5
```

`FRONTEND_API_BASE_URL` 是浏览器实际请求的后端 API 前缀，必须包含 `/api`，例如 `https://api.example.com/api`。使用 `frontend_server.py` 启动前端时，`/js/config.js` 会从 `.env` 动态生成；如果不填写，默认使用 `http://127.0.0.1:${API_PORT}/api`。

`CORS_ORIGINS` 是允许访问后端的前端页面来源，只写协议、域名和端口，不带路径，例如 `https://wiki.example.com`。前后端分离部署时，需要同时修改：

- 前端请求后端：`FRONTEND_API_BASE_URL=https://后端域名/api`
- 后端允许前端跨域：`CORS_ORIGINS=https://前端域名`

### 3. 初始化数据库

无需安装或启动数据库服务。后端首次启动时会自动创建
`DATABASE_PATH` 指向的 SQLite 文件，并执行 `sql/schema.sql` 写入表结构、
示例数据和默认管理员。

如需重新初始化本地数据，请先停止后端并备份或删除 SQLite 文件，再启动后端。

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

当前只保留一个数据库初始化脚本：`sql/schema.sql`。空数据库首次连接时会自动执行该脚本，写入数据库结构、示例数据和默认管理员。初始化后包含这些表：

- `users`：用户账号。密码使用 PBKDF2-HMAC-SHA256 哈希保存，`role` 使用 `admin` / `user` 区分管理员和普通用户。
- `people` / `project_members`：现实人员档案和 CAS 项目成员关系。成员角色、排序和项目内联系方式保存在关系表中；只有管理员可以在 CAS 项目详情的成员区域把人员档案绑定到账号。
- `user_follows` / `user_blocks`：关注和黑名单关系。
- `conversations` / `conversation_members` / `messages`：一对一私信、会话状态和消息记录。
- `announcements`：支持草稿、发布、置顶、归档和浏览量的公告正文。
- `comments` / `comment_likes` / `comment_reports`：公告、CAS 项目和资源共用的两级留言、点赞与举报。
- `comment_notifications`：回复和收到的赞的永久通知、未读状态及原留言定位信息。
- `projects`：CAS 项目。`icon` 保存项目图标图片 URL；`updates` 使用 JSON 文本保存结构化动态，每条动态包含自己的文字和照片数组。`media` 仅保留用于读取旧数据，新后台不再维护项目级媒体。
- `project_categories`：CAS 项目库左侧分类。`sortOrder` 是人工排序权重，数字越小越靠前；分类排序不影响项目本身排序。
- 资源中心类型固定定义在 `backend/resource_types.py`：`yearbook`、`photos`、`teacher`、`other`。这些稳定值会分派到不同处理逻辑，不由数据库动态创建。
- `resources`：资源中心普通资源卡片。`category` 当前包括 `yearbook`、`teacher`、`other`；活动照片不写入该表，统一来自 `photo_activities`。“老师驾到”使用 `resource_url` 保存浏览器可直接播放的视频文件或直链，`image` 在数据库中保存为空字符串；本地视频的接口响应会动态补充首帧缩略图。其他普通资源继续使用 `image` 作为卡片缩略图和详情页封面图。前台卡片展示缩略图，文字只显示标题和年份，点击整张卡片进入资源详情页。
- `photo_activities`：活动照片分组。`description` 是必填活动简介，用于关键词搜索和活动内容展示；活动卡片使用目录中按文件名自然排序的第一张照片作为缩略图，文字只显示标题和年份，不再使用 icon 字段；`sortOrder` 控制左侧活动列表顺序；`downloads` 统计整场活动的照片下载次数。
- `photo_items`：单张活动照片。通过 `activity_id` 关联 `photo_activities.id`，删除活动时照片记录会级联删除。

用户系统提供开放注册、登录和当前用户接口。注册账号默认是普通用户；默认管理员由 `sql/schema.sql` 初始化创建。

用户系统还提供公开资料、关注、黑名单和私信权限。项目成员不要求预先拥有账号：管理员在项目创建后的成员管理中录入姓名、负责人/成员角色及可选联系方式，系统会创建独立人员档案；需要关联站内账号时，由管理员在该 CAS 项目详情的成员卡片中直接绑定。普通用户不能自行认领。联系方式属于该成员在当前项目中的公开资料，不会自动复制到其他项目。系统也不会仅凭姓名自动跨项目合并人员，避免重名误绑。

消息中心位于 `/messages.html`，侧栏仅包含“我的消息”“回复我的”“收到的赞”。所有一对一会话使用同一个私信列表；回复和点赞按时间倒序逐条展示，有效记录可定位原留言，原留言删除或隐藏后通知仍保留并显示失效提示：

- 对方尚未回复、且当前没有关注发送者时，发送者每个北京时间自然日最多发送一条消息。
- 对方回复过一次后永久解除每日限制；对方当前关注发送者时也不受该限制。
- 支持未读数、已读位置、两分钟内撤回、单方隐藏会话、举报和黑名单。
- WebSocket 用一次性短期凭证推送实时事件，断线时前端使用短轮询兜底。

首页只展示最新三条公告，并提供“全部公告”入口。`/announcements.html` 支持搜索和分页，每条公告都可进入独立详情页。公告、CAS 项目和普通资源共用一套两级留言区：登录用户可留言、回复任意楼层、点赞、删除自己的留言和举报他人留言；删除主留言后只隐藏正文，已有回复仍保留。黑名单关系不能通过留言回复绕过。

资源中心采用“查看公开、下载需登录”的权限模型：未登录用户可以浏览资源列表、查看活动照片、打开照片放大预览和阅读 Yearbook 图片页面；点击普通资源文件、Yearbook PDF、活动照片压缩包或单张照片下载时必须登录。前端未登录点击下载会弹出 `抱歉，需要登陆` 并阻止下载。

活动照片整包下载使用照片目录下的同名压缩文件。比如 `photoDir` 为 `/uploads/photos/春季运动会/` 时，请把压缩文件放在 `/uploads/photos/春季运动会/春季运动会.rar`，接口会通过 `archiveUrl` 返回下载地址。活动照片下载量是活动级统计，点击整包下载或在放大弹窗里下载单张照片都会增加 `photo_activities.downloads`。

Yearbook 资源使用 `resources.resource_url` 指向 `public/` 下的一个目录，例如 `/uploads/yearbook/2026/`。目录内放所有页面图片和 PDF 文件；页面图片支持 `.jpg`、`.jpeg`、`.png`、`.webp`、`.gif`。封面不单独维护，自动使用目录内文件名自然升序的第一张图片，并复用活动照片的缩略图逻辑懒生成 `.thumbs/*.webp`。前台卡片使用该缩略图，进入 Yearbook 后会按文件名自然升序展示图片页面，每次显示两页并按两页翻页；双页阅读器优先加载缩略图，点开放大和下载仍使用原图。PDF 下载按钮使用目录内文件名自然升序的第一个 `.pdf`，建议命名为 `yearbook.pdf`。页面图片建议使用 `001.png`、`002.png`、`003.png` 这类带前导零的文件名，避免排序歧义。

资源统计会由前台行为自动维护：点击卡片进入资源详情（包括“老师驾到”视频详情）、打开 Yearbook 阅读器或进入某个活动照片详情都会增加对应热度；所有新资源和新活动的热度固定从 0 开始，后台不提供人工填写入口。热度使用通用节流逻辑，同一登录账户对同一对象 5 秒内只会增加一次。已登录用户点击普通资源链接、Yearbook PDF、Yearbook 单页图片、活动照片整包或活动单张照片下载会增加下载数，下载数不节流；未登录用户会被前端提示登录，不会增加下载数；后台预览和后台下载不计入统计。

活动照片前台接口分为活动列表和单活动照片列表：`/api/photo-activities` 只返回活动摘要、第一张照片的封面和照片数量，进入某个活动后再请求 `/api/photo-activities/{activity_id}/photos` 获取照片。照片目录扫描使用后端进程内缓存，`PHOTO_DIR_CACHE_MINUTES` 控制缓存有效期，单位是分钟。默认 5 分钟内每个活动目录复用同一份照片列表，不重复扫描目录；缓存过期后的下一次访问会重新扫描并为新增照片生成缩略图。设置为 `0` 可关闭缓存，方便开发调试。图片缩略图按最长边不超过 640 像素生成 WebP，质量 82、编码 method 6，并保存为源文件旁的 `.thumbs/<文件主名>.webp`；源文件更新后会自动重建。本地老师视频使用 FFmpeg 提取第一帧，保存为 `.thumbs/<视频主名>.video.webp` 并沿用同一压缩参数；未安装 FFmpeg 或使用外部视频 URL 时不自动生成。

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
昵称：kuxiaowo
姓名：张三
密码：12345678
```

该账号用于本地示例和初始化验证，生产环境请修改密码或删除。

后台只允许 `role = admin` 的用户访问。默认管理员由初始化脚本创建；其他用户可直接通过后台“用户管理”调整为管理员。

管理员登录后可以：

- 查看、创建和编辑用户，并调整 `admin/user` 角色。
- 在文件管理栏目浏览 `public/` 目录，并选择目标文件夹上传文件。
- 在“数据导入/导出”栏目以 JSON 整体迁移 CAS 项目、成员联系方式、项目动态、普通资源和活动照片；进入任一项目或资源的编辑弹窗后也可单独导出。导入前会整批校验，每次导入都创建新记录，不覆盖已有内容；JSON 只记录站内路径或外部 URL，不包含资源文件本身。
- 新建 CAS 项目时只填写名称、分类、年份、图标、简介和 CAS 三要素，不填写负责人。创建后从项目行进入后台详情，在成员区域添加人员、确认负责人/成员身份、填写可选联系方式，并由管理员绑定或解除站内账号；负责人未知时可以暂不设置，确认后最多只能有一名负责人。项目不再单独维护照片/视频，每条动态分别填写文字和自己的照片。正式前台详情页只负责展示。拖拽 CAS 项目库左侧分类可调整分类顺序，分类顺序会同步影响前台项目库。
- 新建、编辑和删除资源中心资源；后台资源管理与前台共同调用 `public/js/resource-ui.js` 渲染资源卡片、活动卡片并执行排序，同时复用同一套筛选条、左侧分类和右侧内容布局。后台只在卡片关键位置叠加“编辑”按钮；点击卡片主体仍进入正式详情页，但以后台预览模式打开，不增加公开热度。
- “老师驾到”属于资源中心固定分类，新建内容时填写名称、简介、年份和视频文件/URL；本地视频的列表卡片显示第一帧缩略图，文字只显示标题和年份，视频仅在详情页公开播放，不要求登录，也不计作下载。
- 资源中心左侧类型及顺序固定；“活动照片”分类下的左侧活动列表仍可拖拽调整顺序。
- 在资源管理中选择“活动照片”分类后，会显示左侧活动筛选、右侧活动卡片和活动照片平铺页；进入某个活动后，可在活动标题/描述区域编辑活动。
- 普通资源和活动照片都只手动填写 URL，或浏览 `public/` 选择已有文件/文件夹；活动照片通过 `photoDir` 绑定到 `public/` 下的文件夹，后台不再单张编辑照片。
- 在“公告与留言”中创建、编辑、置顶和归档公告，并处理公告、项目和资源下的留言举报。

默认上传文件可以保存到：

```text
public/uploads/
```

也可以在后台文件管理中选择 `public/` 下其他子目录作为上传目标。资源地址可以引用具体文件 URL，也可以引用目录 URL，例如 `/uploads/activity-2026/`。

前端静态服务会直接放行图片和视频文件，保证照片、Yearbook 页面和“老师驾到”视频可以匿名查看；会拒绝直接访问 `.pdf`、`.zip`、`.rar`、`.7z`、Office 文档等下载型文件。下载这类文件应走后端 `/api/files/{file_path}`，由登录状态校验后作为附件返回。

数据库查看器和在线修复结构功能已经删除。结构变更应通过版本化迁移脚本完成；当前首次建库统一执行 `sql/schema.sql`。

后端启动时会在初始化脚本之后按编号执行 `sql/migrations/*.sql`。现有版本 1 数据库会依次应用后续迁移，最终升级到 `user_version = 7`。其中 002 会回填项目成员档案，003 会建立公告和通用留言表，004 会移除已经由代码固定定义的资源分类表，005 会为项目成员关系增加联系方式字段，006 会移除旧消息请求状态并统一私信会话，007 会建立回复与点赞通知表且不回填历史互动。

`sortOrder` 表示人工排序权重，数字越小越靠前。后台拖拽会自动维护为 `10, 20, 30...`；当前用于 CAS 项目分类和活动列表，不用于固定资源类型、普通项目、普通资源卡片或单张照片卡片。

后端上传接口依赖 `python-multipart`，安装依赖时请执行：

```bash
python3 -m pip install -r requirements.txt
```
