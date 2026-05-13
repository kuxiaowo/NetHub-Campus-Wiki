# 代码规范

## 总体原则

- 前端、后端、数据库脚本分目录维护，不把职责混在同一个文件里。
- 所有文本文件统一使用 UTF-8 编码。
- 配置通过 `.env` 或 `public/js/config.js` 管理，不在业务代码里写死环境差异。
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
- API 地址只在 `public/js/config.js` 配置。
- CSS 按页面区域分区组织，避免为单个页面随意新增零散样式。

## 命名规范

- Python 文件和函数使用 `snake_case`。
- JavaScript 变量和函数使用 `camelCase`。
- CSS class 使用短横线命名，例如 `project-card`。
- API JSON 字段面向前端使用 `camelCase`，数据库字段使用 `snake_case`。
