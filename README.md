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
├── scripts/
│   ├── init_linux.sh          # 同时初始化前后端
│   ├── init_frontend_linux.sh # 仅初始化前端
│   └── init_backend_linux.sh  # 仅初始化后端
├── sql/schema.sql         # 只创建 SQLite 结构的初始化脚本
├── requirements-frontend.txt # 前端静态服务依赖
└── requirements.txt          # 后端及一键部署依赖
```

## Linux 部署

需要 Linux、systemd 和当前用户可调用的 Conda。脚本不使用 root，会把服务安装到
`~/.config/systemd/user/`。先检查 `.env.example`，再按部署方式选择一个入口。

在同一台服务器部署前后端：

```bash
cp .env.example .env
# 按实际域名、端口和容量限制编辑 .env
bash scripts/init_linux.sh --admin your_admin --display-name "管理员"
```

仅部署后端：

```bash
cp .env.example .env
# 设置后端端口、CORS、数据库路径等配置
bash scripts/init_backend_linux.sh --admin your_admin --display-name "管理员"
```

仅部署前端：

```bash
cp .env.example .env
# 分机部署时必须把 FRONTEND_API_BASE_URL 设置为后端的完整 /api 地址
bash scripts/init_frontend_linux.sh
```

后端或一键脚本通过 `--admin` 创建管理员时，密码由终端交互读取，不会写入命令行历史。
三个脚本均可重复执行，并会：

- 三个入口都会创建或复用 `.env` 中 `CONDA_ENV_NAME` 指定的 Conda 环境；
- 后端入口安装 `requirements.txt`、生成缺失的 `AUTH_SECRET_KEY`、初始化数据库，
  并只创建和启动 `<前缀>-api.service`；
- 前端入口只安装 `requirements-frontend.txt`，并只创建和启动
  `<前缀>-frontend.service`，不会初始化数据库或操作 API 服务；
- 原 `init_linux.sh` 保持一键部署行为，同时创建并启动两个服务。

脚本只操作当前入口负责的服务，不会停止或删除之前部署的另一项服务。前后端分机部署时，
前端服务器的 `FRONTEND_API_BASE_URL` 必须设置为后端的完整 API 前缀，例如
`https://api.example.com/api`；后端服务器的 `CORS_ORIGINS` 必须包含前端页面来源，例如
`https://wiki.example.com`。

常用维护命令：

```bash
systemctl --user status nethub-campus-wiki-api nethub-campus-wiki-frontend
systemctl --user restart nethub-campus-wiki-api nethub-campus-wiki-frontend
journalctl --user -u nethub-campus-wiki-api -u nethub-campus-wiki-frontend -f
```

systemd 用户服务默认在用户登录后运行。如果还需要“服务器重启后、用户未登录也自动运行”，
由系统管理员执行 `loginctl enable-linger <Linux用户名>`。初始化脚本只提示该操作，避免暗中提权。

## `.env` 配置

所有需要随部署调整的运行参数都列在 `.env.example`，包括：

- 初始化：`CONDA_ENV_NAME`、`PYTHON_VERSION`、`SYSTEMD_SERVICE_PREFIX`；
- 服务：`API_HOST`、`API_PORT`、`API_RELOAD`、`FRONTEND_HOST`、`FRONTEND_PORT`；
- 浏览器访问：`FRONTEND_API_BASE_URL`、`CORS_ORIGINS`；
- SQLite：`DATABASE_PATH`、连接超时和 busy timeout；
- 认证：`AUTH_SECRET_KEY`、Token 有效期；
- 文件处理：上传/导入大小、照片缓存、缩略图尺寸/质量/超时；
- 交互限制：热度节流、私信长度/撤回/频率、留言长度/频率。

环境变量优先于 `.env` 中的同名值。修改配置后需要重启对应服务。资源类型、允许的
文件扩展名和导入格式版本属于程序/安全契约，不作为部署开关。

`FRONTEND_HOST=0.0.0.0` 使前端监听所有网卡。`FRONTEND_API_BASE_URL` 是浏览器实际请求的后端 API 前缀，必须包含 `/api`，例如 `https://api.example.com/api`。使用 `frontend_server.py` 启动前端时，`/js/config.js` 会动态生成；如果不填写，API 地址会自动使用当前页面的主机名和 `API_PORT`，因此从其他设备通过局域网 IP 打开时无需再改 API 地址。

`CORS_ORIGINS` 是允许访问后端的前端页面来源。默认的 `*` 便于从任意本机或局域网地址访问；正式公网部署时建议改为明确的协议、域名和端口，不带路径，例如 `https://wiki.example.com`。前后端分离部署时，需要同时修改：

- 前端请求后端：`FRONTEND_API_BASE_URL=https://后端域名/api`
- 后端允许前端跨域：`CORS_ORIGINS=https://前端域名`

`AUTH_SECRET_KEY` 是登录 Token 的签名密钥，必须为每个部署单独随机生成，不能留空或复制公开示例。Linux 初始化脚本会在其留空时自动生成；手动部署可用：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

后端会在启动时拒绝缺失、旧占位值或不足 32 字节的密钥。更换该值会立即使已有登录 Token 失效。

## 手动开发运行

未使用 Linux 初始化脚本时，建议使用 Conda：

```bash
conda create -n nethub-campus-wiki python=3.12 -y
conda activate nethub-campus-wiki
python -m pip install -r requirements.txt
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
# 将上一行结果写入 .env 的 AUTH_SECRET_KEY
```

无需安装或启动数据库服务。后端首次启动时会自动创建
`DATABASE_PATH` 指向的 SQLite 文件，并执行 `sql/schema.sql` 写入表结构、
再执行 `sql/migrations/*.sql`。初始化不会插入业务数据，也不会创建账号。

如需重新初始化本地数据，请先停止后端并备份或删除 SQLite 文件，再启动后端。

首次部署且数据库中还没有启用中的管理员时，执行交互式引导命令：

```bash
python -m backend.bootstrap_admin --username your_admin --display-name "管理员"
```

该命令只允许创建首个启用中的管理员；已有管理员时会拒绝执行。

启动后端 API 服务（监听地址、端口和 reload 均读取 `.env`）：

```bash
python -m backend.main
```

后端地址：

- API 健康检查：http://127.0.0.1:3100/api/health
- 自动接口文档：http://127.0.0.1:3100/docs

另开一个终端启动前端：

```bash
python frontend_server.py
```

前端地址：

- 首页：http://127.0.0.1:3200/
- CAS 项目库：http://127.0.0.1:3200/projects.html

其他设备请使用运行此项目的电脑实际 IP，例如 `http://192.168.1.20:3200/`。`0.0.0.0` 是服务端的监听地址，不是供其他设备访问的目标地址。Windows 防火墙也需允许 Python 或 3100/3200 端口的入站连接。

如果后端端口或域名变化，修改 `.env` 中的 `FRONTEND_API_BASE_URL`，然后重启前端服务。后端的 `CORS_ORIGINS` 也要包含当前前端页面的来源，否则浏览器会拦截跨域请求。

## 数据库结构

当前只保留一个数据库初始化脚本：`sql/schema.sql`。空数据库首次连接时会自动执行该脚本，只写入数据库结构，不写入示例业务数据或账号。初始化后包含这些表：

- `users`：用户账号。密码使用 PBKDF2-HMAC-SHA256 哈希保存，`role` 使用 `admin` / `user` 区分管理员和普通用户。
- `people` / `project_members`：现实人员档案和 CAS 项目成员关系。成员角色、排序和项目内联系方式保存在关系表中；只有管理员可以在 CAS 项目详情的成员区域把人员档案绑定到账号。
- `user_follows` / `user_blocks`：关注和黑名单关系。
- `conversations` / `conversation_members` / `messages`：一对一私信、会话状态和消息记录。
- `announcements`：支持发布、置顶、归档、永久删除和浏览量的公告正文。
- `comments` / `comment_likes` / `comment_reports`：公告、CAS 项目和资源共用的两级留言、点赞与举报。
- `comment_notifications`：回复和收到的赞的永久通知、未读状态及原留言定位信息。
- `projects`：CAS 项目。`icon` 保存项目图标图片 URL；`updates` 使用 JSON 文本保存结构化动态，每条动态包含自己的文字和照片数组。`media` 仅保留用于读取旧数据，新后台不再维护项目级媒体。
- `project_categories`：CAS 项目库左侧分类。`sortOrder` 是人工排序权重，数字越小越靠前；分类排序不影响项目本身排序。
- 资源中心类型固定定义在 `backend/resource_types.py`：`yearbook`、`photos`、`teacher`、`other`。这些稳定值会分派到不同处理逻辑，不由数据库动态创建。
- `resources`：资源中心普通资源卡片。`category` 当前包括 `yearbook`、`teacher`、`other`；活动照片不写入该表，统一来自 `photo_activities`。“老师驾到”使用 `resource_url` 保存浏览器可直接播放的视频文件或直链，`image` 可保存选填的自定义封面；没有自定义封面时，本地视频的接口响应会动态补充首帧缩略图。其他普通资源继续使用 `image` 作为卡片缩略图和详情页封面图。前台卡片展示缩略图，文字只显示标题和年份，点击整张卡片进入资源详情页。
- `photo_activities`：活动照片分组。`description` 是必填活动简介，用于关键词搜索和活动内容展示；`coverImage` 可选填自定义封面地址，未填写时活动卡片使用目录中按文件名自然排序的第一张照片；`sortOrder` 控制左侧活动列表顺序；`downloads` 统计整场活动的照片下载次数。
- `photo_items`：单张活动照片。通过 `activity_id` 关联 `photo_activities.id`，删除活动时照片记录会级联删除。

用户系统提供开放注册、登录和当前用户接口。注册账号默认是普通用户；首个管理员必须通过 `python -m backend.bootstrap_admin` 在服务器终端显式创建。

注册、登录和修改密码接口使用数据库持久化限流。默认限制为：普通登录每 IP 每分钟 10 次，管理员登录额外限制为每 IP 每分钟 5 次；同一用户名连续失败 5 次后冷却 10 分钟；注册每 IP 每小时 3 次且每日 10 次；修改密码每用户及每 IP 每小时 5 次。管理员可在后台“访问限制”栏目修改这些数值，保存后即时生效。限流响应为 `429 Too Many Requests` 并包含 `Retry-After`。

用户系统还提供公开资料、关注、黑名单和私信权限。项目成员不要求预先拥有账号：管理员在项目创建后的成员管理中录入姓名、负责人/成员角色及可选联系方式，系统会创建独立人员档案；需要关联站内账号时，由管理员在该 CAS 项目详情的成员卡片中直接绑定。普通用户不能自行认领。联系方式属于该成员在当前项目中的公开资料，不会自动复制到其他项目。系统也不会仅凭姓名自动跨项目合并人员，避免重名误绑。

消息中心位于 `/messages.html`，侧栏仅包含“我的消息”“回复我的”“收到的赞”。所有一对一会话使用同一个私信列表；回复和点赞按时间倒序逐条展示，有效记录可定位原留言，原留言删除或隐藏后通知仍保留并显示失效提示：

- 对方尚未回复、且当前没有关注发送者时，发送者每个北京时间自然日最多发送一条消息。
- 对方回复过一次后永久解除每日限制；对方当前关注发送者时也不受该限制。
- 支持未读数、已读位置、限时撤回、单方隐藏会话、举报和黑名单；撤回时限由 `MESSAGE_RECALL_WINDOW_SECONDS` 控制。
- WebSocket 用一次性短期凭证推送实时事件，断线时前端使用短轮询兜底。

首页只展示最新三条公告，并提供“全部公告”入口。`/announcements.html` 支持搜索和分页，每条公告都可进入独立详情页。公告、CAS 项目和普通资源共用一套两级留言区：登录用户可留言、回复任意楼层、点赞、删除自己的留言和举报他人留言；删除主留言后只隐藏正文，已有回复仍保留。黑名单关系不能通过留言回复绕过。

资源中心采用“查看公开、下载需登录”的权限模型：未登录用户可以浏览资源列表、查看活动照片、打开照片放大预览和阅读 Yearbook 图片页面；点击普通资源文件、Yearbook PDF、活动照片批量下载或单张照片下载时必须登录。前端未登录点击下载会弹出 `抱歉，需要登陆` 并阻止下载。

活动照片不再配置或保存压缩包。点击“下载全部照片”后，支持 File System Access API 的浏览器会请用户选择下载位置，再创建 `年份-活动名称` 文件夹并以 3 个并发任务逐张流式写入原图。该能力要求 HTTPS（localhost 例外），推荐使用最新版 Chrome 或 Edge。Safari、Firefox 或非安全上下文不支持目录选择时，前端会明确提示只能批量下载到浏览器默认下载目录，经用户确认后分批触发单文件下载。浏览器可能额外询问是否允许多个文件下载。每次至少成功保存或提交一张照片后，会增加一次 `photo_activities.downloads`；在放大弹窗里下载单张照片也会增加该统计。

Yearbook 资源使用 `resources.resource_url` 指向 `public/` 下的一个目录，例如 `/uploads/yearbook/2026/`。目录内放所有页面图片和 PDF 文件；页面图片支持 `.jpg`、`.jpeg`、`.png`、`.webp`、`.gif`。封面不单独维护，自动使用目录内文件名自然升序的第一张图片，并复用活动照片的缩略图逻辑懒生成 `.thumbs/*.webp`。前台卡片使用该缩略图，进入 Yearbook 后会按文件名自然升序展示图片页面，每次显示两页并按两页翻页；双页阅读器优先加载缩略图，点开放大和下载仍使用原图。PDF 下载按钮使用目录内文件名自然升序的第一个 `.pdf`，建议命名为 `yearbook.pdf`。页面图片建议使用 `001.png`、`002.png`、`003.png` 这类带前导零的文件名，避免排序歧义。

资源统计会由前台行为自动维护：点击卡片进入资源详情（包括“老师驾到”视频详情）、打开 Yearbook 阅读器或进入某个活动照片详情都会增加对应热度；所有新资源和新活动的热度固定从 0 开始，后台不提供人工填写入口。热度使用通用节流逻辑，窗口由 `RESOURCE_HOT_THROTTLE_SECONDS` 控制（默认 5 秒）。已登录用户点击普通资源链接、Yearbook PDF、Yearbook 单页图片、活动照片整包或活动单张照片下载会增加下载数，下载数不节流；未登录用户会被前端提示登录，不会增加下载数；后台预览和后台下载不计入统计。

活动照片前台接口分为活动列表和单活动照片列表：`/api/photo-activities` 只返回活动摘要、第一张照片的封面和照片数量，进入某个活动后再请求 `/api/photo-activities/{activity_id}/photos` 获取照片。照片目录扫描使用后端进程内缓存，`PHOTO_DIR_CACHE_MINUTES` 控制缓存有效期，单位是分钟；设置为 `0` 可关闭缓存。缩略图尺寸、WebP 质量、编码 method 和视频截帧超时均由 `.env` 的 `THUMBNAIL_*` / `VIDEO_THUMBNAIL_TIMEOUT_SECONDS` 控制，并保存为源文件旁的 `.thumbs/`；源文件更新后会自动重建。本地老师视频使用 FFmpeg 提取第一帧，未安装 FFmpeg 或使用外部视频 URL 时不自动生成。前端静态服务支持单段 HTTP Range 请求并返回 `206 Partial Content`，使浏览器可以按需加载和跳转视频；本地 MP4 建议使用 FFmpeg `-movflags +faststart` 将 `moov` 索引放在媒体数据之前。

## 代码规范

- 后端只负责 API、数据访问和响应模型，不再托管前端页面。
- 前端只负责页面渲染和用户交互，通过 `public/js/api.js` 调用后端。
- 环境差异和可调运行参数通过 `.env` 配置；前端运行时的 `/js/config.js` 由 `frontend_server.py` 根据 `.env` 生成。
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

后台只允许 `role = admin` 的用户访问。项目不再提供默认管理员或固定密码；首次部署使用上文的交互式引导命令创建管理员，之后可通过后台“用户管理”调整其他用户的角色。

管理员登录后可以：

- 查看、创建和编辑用户，并调整 `admin/user` 角色。
- 在文件管理栏目浏览 `public/` 目录，在当前目录新建文件夹、上传单个文件，或直接上传并保留内部结构的整个文件夹。
- 在“数据导入/导出”栏目以 JSON v2 整体迁移 CAS 项目、成员联系方式、项目动态、普通资源和活动照片；进入任一项目或资源的编辑弹窗后也可单独导出。导入前会整批校验，每次导入都创建新记录，不覆盖已有内容；CAS 项目只记录资源目录和目录内相对图片路径，不包含实体文件。
- 新建 CAS 项目时填写名称、分类、年份、`public/CAS/` 下的项目资源目录、简介和 CAS 三要素，不填写负责人。图标使用项目目录内固定的 `icon.*` 文件。创建后从项目行进入后台详情，在成员区域管理人员和联系方式；动态可选择项目目录中的已有照片，也可直接多图上传到自动创建的 `updates/<动态ID>/` 子目录。项目不再单独维护照片/视频。正式前台详情页只负责展示。拖拽 CAS 项目库左侧分类可调整分类顺序，分类顺序会同步影响前台项目库。
- 新建、编辑和删除资源中心资源；后台资源管理与前台共同调用 `public/js/resource-ui.js` 渲染资源卡片、活动卡片并执行排序，同时复用同一套筛选条、左侧分类和右侧内容布局。后台只在卡片关键位置叠加“编辑”按钮；点击卡片主体仍进入正式详情页，但以后台预览模式打开，不增加公开热度。
- “老师驾到”属于资源中心固定分类。在资源管理中选中该分类后，新建资源表单会默认选择“老师驾到”；表单仍提供分类下拉框，选择分类后会在同一弹窗内立即切换并绑定对应字段模板，避免分类值与表单格式错位。名称、年份和视频文件/URL 必填，简介与封面选填。填写封面时会优先用于卡片和播放器，未填写时本地视频使用自动提取的第一帧。视频仅在详情页公开播放，不要求登录，也不计作下载。
- 资源中心左侧类型及顺序固定；“活动照片”分类下的左侧活动列表仍可拖拽调整顺序。
- 在资源管理中选择“活动照片”分类后，会显示左侧活动筛选、右侧活动卡片和活动照片平铺页；进入某个活动后，可在活动标题/描述区域编辑活动。
- 普通资源和活动照片都只手动填写 URL，或浏览 `public/` 选择已有文件/文件夹；活动照片通过 `photoDir` 绑定到 `public/` 下的文件夹，后台不再单张编辑照片。
- 在“公告与留言”中创建、编辑、置顶、归档或永久删除公告，并处理公告、项目和资源下的留言举报。
- 在“访问限制”中调整注册、普通/管理员登录、连续失败冷却及修改密码的请求限额；保存后无需重启服务。

默认上传文件可以保存到：

```text
public/uploads/
```

也可以在后台文件管理中选择 `public/` 下其他子目录作为上传目标。上传文件夹时会保留顶层文件夹名称、文件名和内部目录结构；若当前目录已经存在同名文件夹，系统会拒绝合并，以免覆盖原文件。资源地址可以引用具体文件 URL，也可以引用目录 URL，例如 `/uploads/activity-2026/`。

前端静态服务会直接放行图片和视频文件，保证照片、Yearbook 页面和“老师驾到”视频可以匿名查看；视频等公开静态文件支持 HTTP Range 分段读取和快进。服务会拒绝直接访问 `.pdf`、`.zip`、`.rar`、`.7z`、Office 文档等下载型文件。下载这类文件应走后端 `/api/files/{file_path}`，由登录状态校验后作为附件返回。

数据库查看器和在线修复结构功能已经删除。结构变更应通过版本化迁移脚本完成；当前首次建库统一执行 `sql/schema.sql`。

后端启动时会在初始化脚本之后按编号执行 `sql/migrations/*.sql`。现有数据库会依次应用后续迁移，最终升级到 `user_version = 13`。其中 002 会回填项目成员档案，003 会建立公告和通用留言表，004 会移除已经由代码固定定义的资源分类表，005 会为项目成员关系增加联系方式字段，006 会移除旧消息请求状态并统一私信会话，007 会建立回复与点赞通知表且不回填历史互动，008 会增加 CAS 项目资源目录并把可识别的旧动态图片 URL 转为相对路径，009 会降权并禁用仍在使用公开初始密码哈希的旧默认管理员，010—011 增加用户注销、公告状态和认证限流能力，012 统一 CAS 成员中英文姓名顺序，013 增加活动照片可选封面并启用 Yearbook 可选自定义封面。

`sortOrder` 表示人工排序权重，数字越小越靠前。后台拖拽会自动维护为 `10, 20, 30...`；当前用于 CAS 项目分类和活动列表，不用于固定资源类型、普通项目、普通资源卡片或单张照片卡片。

后端上传接口依赖 `python-multipart`，安装依赖时请执行：

```bash
python3 -m pip install -r requirements.txt
```
