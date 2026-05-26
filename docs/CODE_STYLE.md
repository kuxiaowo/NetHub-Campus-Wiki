# 代码规范

## 总体原则

- 前端、后端、数据库脚本分目录维护，不把职责混在同一个文件里。
- 所有文本文件统一使用 UTF-8 编码。
- 配置通过 `.env` 管理；前端运行时配置由 `frontend_server.py` 生成 `/js/config.js`，不在业务代码里写死环境差异。
- 注释解释“为什么这样做”和“模块职责”，避免重复描述每一行代码。

## 后端规范

- 路由入口放在 `backend/main.py`。
- 数据库连接放在 `backend/database.py`。
- 数据查询和字段映射放在 `backend/projects.py`。
- 响应结构放在 `backend/schemas.py`，通过 Pydantic 自动生成接口文档。
- SQL 查询必须使用参数绑定，不把用户输入直接拼进 SQL。
- 新增接口时必须同步更新 `docs/API.md`。

## 前端规范

- 页面 HTML 只保留结构，业务逻辑放在 `public/js/`。
- 公共 API 请求和通用渲染工具放在 `public/js/api.js`。
- 所有接口返回的数据进入 `innerHTML` 前必须经过 `escapeHtml`。
- API 地址通过 `.env` 中的 `FRONTEND_API_BASE_URL` 配置，`public/js/api.js` 只读取运行时注入的 `window.CAMPUS_WIKI_CONFIG`。
- CSS 按页面区域分区组织，避免为单个页面随意新增零散样式。

## 命名规范

- Python 文件和函数使用 `snake_case`。
- JavaScript 变量和函数使用 `camelCase`。
- CSS class 使用短横线命名，例如 `project-card`。
- API JSON 字段面向前端使用 `camelCase`，数据库字段使用 `snake_case`。

## 管理后台代码规范

- 后台接口统一使用 `/api/admin/...` 路径，并且必须依赖管理员权限校验。
- 后台写接口仍然使用参数绑定 SQL，不允许拼接用户输入。
- 数据库查看器只能访问白名单表，不允许提供任意 SQL 输入框或执行接口。
- `users.password_hash` 不允许返回给前端，也不允许通过数据库查看器编辑。
- 上传接口必须校验扩展名、限制文件大小；普通文件使用随机文件名保存到 `public/uploads/`，活动照片 `.rar` 压缩文件保留原文件名以支持同名下载。
- 文件管理接口必须把所有传入路径解析到仓库 `public/` 内，拒绝 `..` 和以 `/` 开头的绝对路径。
- 上传文件和编辑内容必须职责分离：文件管理负责上传，资源和照片编辑只保存 URL 引用。
- 活动照片归属于后台资源管理的 `photos` 分类；活动记录只维护 `photoDir`，不做独立后台栏目，也不在后台单张编辑照片。
- 后台前端渲染接口数据进入 `innerHTML` 前必须使用 `escapeHtml`。
- 文件上传请求使用 `FormData`，不能手动设置 `Content-Type`。
- 新增或变更后台接口后，必须同步更新 `docs/API.md`；变更数据约束后，必须同步更新 `docs/DATABASE.md`。
