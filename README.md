# Campus Wiki 校园论坛 + CAS 项目库

这是一个前后端分离的校园项目展示原型，包含首页公告、CAS 项目库、项目筛选和项目详情。

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
│   └── schemas.py         # API 响应模型
├── public/
│   ├── index.html         # 首页
│   ├── projects.html      # CAS 项目库
│   ├── detail.html        # 项目详情
│   ├── css/styles.css
│   └── js/
│       ├── config.js      # 前端 API 地址配置
│       ├── api.js         # Fetch 封装和通用渲染
│       ├── index.js
│       ├── projects.js
│       └── detail.js
├── docs/API.md            # 详细接口文档
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
```

### 3. 初始化数据库

确保 MySQL 已启动，然后导入示例数据：

```bash
mysql -u campus_user -p -h 127.0.0.1 campus_cas_forum < sql/schema.sql
```

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

## 代码规范

- 后端只负责 API、数据访问和响应模型，不再托管前端页面。
- 前端只负责页面渲染和用户交互，通过 `public/js/api.js` 调用后端。
- 环境差异通过 `.env` 和 `public/js/config.js` 配置，不把数据库账号写死到业务代码中。
- API 响应统一使用 JSON；项目列表和详情都返回 `{ "data": ... }`。
- 数据库访问集中在 `backend/database.py` 和 `backend/projects.py`，路由层不直接拼装业务数据。
- CSS 使用稳定尺寸和明确布局，导航位于网站名右侧，移动端自动换行。
- 更详细的团队代码规范见 [docs/CODE_STYLE.md](docs/CODE_STYLE.md)。

## 接口文档

详细接口见 [docs/API.md](docs/API.md)。运行后端后，也可以访问 FastAPI 自动生成的 OpenAPI 文档：

```text
http://127.0.0.1:3100/docs
```
