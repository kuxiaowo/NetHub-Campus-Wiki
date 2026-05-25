# Campus Wiki API 文档

基础地址：

```text
http://127.0.0.1:3100
```

所有业务接口都以 `/api` 开头，响应格式为 JSON。前端默认从 `public/js/config.js` 读取：

```javascript
window.CAMPUS_WIKI_CONFIG = {
  apiBaseUrl: 'http://127.0.0.1:3100/api',
};
```

## 通用约定

- 字符编码：UTF-8
- 时间格式：ISO 8601 字符串，例如 `2026-05-10T10:00:00`
- 排序参数：只接受文档列出的枚举值
- 错误响应：FastAPI 默认错误结构，例如 `{"detail": "项目不存在"}`
- 跨域：后端通过 `CORS_ORIGINS` 环境变量允许前端服务访问
- 登录鉴权：需要登录的接口使用 `Authorization: Bearer <accessToken>`

## 用户结构

认证接口中的 `User` 使用以下结构：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `number` | 用户 ID |
| `username` | `string` | 登录用户名 |
| `displayName` | `string \| null` | 展示名称 |
| `role` | `"admin" \| "user"` | 用户角色，`admin` 为管理员，`user` 为普通用户 |
| `isActive` | `boolean` | 账号是否启用 |
| `createdAt` | `string \| null` | 创建时间 |

## POST /api/auth/register

开放注册普通用户。注册成功后角色固定为 `user`。

### 请求示例

```bash
curl -X POST http://127.0.0.1:3100/api/auth/register \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"student01\",\"password\":\"password123\",\"displayName\":\"学生 01\"}"
```

### 请求字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `username` | `string` | 是 | 3-32 位，只允许字母、数字和下划线 |
| `password` | `string` | 是 | 至少 8 位 |
| `displayName` | `string` | 否 | 展示名称 |

### 成功响应

返回 `User`。

### 常见错误

- `409 Conflict`：用户名已存在。
- `422 Unprocessable Entity`：用户名或密码格式不符合要求。

## POST /api/auth/login

使用用户名和密码登录，返回 Bearer Token。

### 请求示例

```bash
curl -X POST http://127.0.0.1:3100/api/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"student01\",\"password\":\"password123\"}"
```

### 成功响应

```json
{
  "accessToken": "header.payload.signature",
  "tokenType": "bearer",
  "user": {
    "id": 1,
    "username": "student01",
    "displayName": "学生 01",
    "role": "user",
    "isActive": true,
    "createdAt": "2026-05-21T12:00:00"
  }
}
```

### 常见错误

- `401 Unauthorized`：用户名或密码错误。
- `403 Forbidden`：账号已被禁用。

## GET /api/auth/me

读取当前登录用户。

### 请求示例

```bash
curl http://127.0.0.1:3100/api/auth/me \
  -H "Authorization: Bearer <accessToken>"
```

### 成功响应

返回 `User`。

### 常见错误

- `401 Unauthorized`：缺少 token、token 无效或 token 已过期。
- `403 Forbidden`：账号已被禁用。

## GET /api/health

检查 API 服务和数据库连接状态。

### 请求示例

```bash
curl http://127.0.0.1:3100/api/health
```

### 成功响应

```json
{
  "ok": true,
  "database": "connected",
  "message": null,
  "detail": null
}
```

### 数据库不可用响应

```json
{
  "ok": false,
  "database": null,
  "message": "数据库连接失败",
  "detail": "具体数据库错误信息"
}
```

## GET /api/announcements

获取首页公告列表。

### 请求示例

```bash
curl http://127.0.0.1:3100/api/announcements
```

### 响应字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `data` | `string[]` | 公告文本列表 |

### 响应示例

```json
{
  "data": [
    "CAS 项目库原型上线：欢迎提交你的项目资料。",
    "本周五 16:00 将举办 CAS 项目分享会。"
  ]
}
```

## GET /api/meta

获取项目筛选器需要的分类和年份。

### 请求示例

```bash
curl http://127.0.0.1:3100/api/meta
```

### 响应字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `categories` | `string[]` | 所有项目分类，按名称升序 |
| `years` | `number[]` | 所有项目年份，按年份降序 |

### 响应示例

```json
{
  "categories": ["公益服务", "科技创新", "运动健康"],
  "years": [2026, 2025]
}
```

## GET /api/projects

获取项目列表，支持分类、年份、关键词和排序。

### 查询参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `category` | `string` | 否 | 无 | 按项目分类精确筛选 |
| `year` | `number` | 否 | 无 | 按项目年份筛选 |
| `search` | `string` | 否 | 无 | 搜索项目名称、负责人和简介 |
| `sort` | `string` | 否 | `latest` | `latest` 按创建时间排序，`popular` 按热度排序 |

### 请求示例

```bash
curl "http://127.0.0.1:3100/api/projects?category=科技创新&year=2026&sort=popular"
```

### 响应字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `data` | `Project[]` | 符合筛选条件的项目列表 |

### Project 结构

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `number` | 项目 ID |
| `name` | `string` | 项目名称 |
| `leader` | `string` | 负责人 |
| `members` | `string` | 成员描述 |
| `category` | `string` | 项目分类 |
| `year` | `number` | 项目年份 |
| `icon` | `string` | 项目图标图片 URL |
| `description` | `string` | 项目简介 |
| `media` | `string[]` | 图片或视频链接 |
| `cas` | `object` | CAS 三项标记 |
| `cas.creativity` | `boolean` | 是否包含 Creativity |
| `cas.activity` | `boolean` | 是否包含 Activity |
| `cas.service` | `boolean` | 是否包含 Service |
| `popularity` | `number` | 热度分 |
| `updates` | `string[]` | 项目动态 |
| `createdAt` | `string | null` | 创建时间 |
| `updatedAt` | `string | null` | 更新时间 |

### 响应示例

```json
{
  "data": [
    {
      "id": 1,
      "name": "校园噪音地图",
      "leader": "李明",
      "members": "李明, 王小雨, Chen Alex",
      "category": "科技创新",
      "year": 2026,
      "icon": "https://picsum.photos/seed/noise-map-icon/300/300",
      "description": "使用传感器采集校园不同地点的噪音数据。",
      "media": ["https://picsum.photos/seed/noise-map/900/520"],
      "cas": {
        "creativity": true,
        "activity": true,
        "service": true
      },
      "popularity": 96,
      "updates": ["完成第一版传感器数据模拟器"],
      "createdAt": "2026-05-10T10:00:00",
      "updatedAt": "2026-05-10T10:00:00"
    }
  ]
}
```

### 参数错误

`sort` 只允许 `latest` 或 `popular`。传入其他值会返回 `422 Unprocessable Entity`。

## GET /api/projects/{project_id}

获取单个项目详情。

### 路径参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `project_id` | `number` | 是 | 项目 ID |

### 请求示例

```bash
curl http://127.0.0.1:3100/api/projects/1
```

### 成功响应

```json
{
  "data": {
    "id": 1,
    "name": "校园噪音地图",
    "leader": "李明",
    "members": "李明, 王小雨, Chen Alex",
    "category": "科技创新",
    "year": 2026,
    "icon": "https://picsum.photos/seed/noise-map-icon/300/300",
    "description": "使用传感器采集校园不同地点的噪音数据。",
    "media": ["https://picsum.photos/seed/noise-map/900/520"],
    "cas": {
      "creativity": true,
      "activity": true,
      "service": true
    },
    "popularity": 96,
    "updates": ["完成第一版传感器数据模拟器"],
    "createdAt": "2026-05-10T10:00:00",
    "updatedAt": "2026-05-10T10:00:00"
  }
}
```

### 不存在响应

状态码：`404 Not Found`

```json
{
  "detail": "项目不存在"
}
```

## GET /api/resources/meta

获取资源中心筛选器需要的资源分类、资源年份和照片活动年份。

### 请求示例

```bash
curl http://127.0.0.1:3100/api/resources/meta
```

### 响应字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `categories` | `ResourceCategory[]` | 可筛选资源分类 |
| `categories[].value` | `string` | 查询参数使用的分类值 |
| `categories[].label` | `string` | 页面展示名称 |
| `categories[].sortOrder` | `number` | 分类人工排序权重，数字越小越靠前 |
| `years` | `number[]` | 资源年份 |
| `photoYears` | `number[]` | 照片活动年份 |

资源中心前端使用同一组顶部筛选控件服务不同分类：选择“全部资源”时会同时请求 `/api/resources` 和 `/api/photo-activities`，把普通资源和所有活动照片活动混合展示，并过滤旧的 `resources.category = "photos"` 入口；选择普通资源分类时只请求 `/api/resources`；选择 `photos` 活动照片分类时请求 `/api/photo-activities` 获取活动列表，进入某个活动后再请求 `/api/photo-activities/{activity_id}/photos` 获取照片。

## GET /api/resources

获取资源中心普通资源列表，支持分类、年份、关键词和排序。

### 查询参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `category` | `string` | 否 | 无 | 按资源分类筛选，例如 `yearbook`、`other`；活动照片使用 `/api/photo-activities` |
| `year` | `number` | 否 | 无 | 按资源年份筛选 |
| `search` | `string` | 否 | 无 | 搜索资源标题、简介、分类展示名和类型 |
| `sort` | `string` | 否 | `hot` | `hot`、`new`、`old` 或 `download` |

### 响应字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `data` | `Resource[]` | 符合筛选条件的资源列表 |

### Resource 结构

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `number` | 资源 ID |
| `title` | `string` | 资源标题 |
| `description` | `string` | 资源简介 |
| `year` | `number` | 资源年份 |
| `category` | `string` | 资源分类值 |
| `label` | `string` | 资源分类展示名 |
| `type` | `string` | 资源类型展示名 |
| `hot` | `number` | 热度 |
| `downloads` | `number` | 下载次数 |
| `image` | `string` | 封面图 URL |
| `resourceUrl` | `string` | 资源访问或下载 URL |
| `createdAt` | `string | null` | 创建时间 |
| `updatedAt` | `string | null` | 更新时间 |

资源中心卡片不再使用 icon 字段；封面统一来自 `image`。

### 参数错误

`sort` 只允许 `hot`、`new`、`old` 或 `download`。传入其他值会返回 `422 Unprocessable Entity`。

## GET /api/photo-activities

获取活动照片活动列表。资源中心选择“活动照片”分类时使用此接口；“全部活动”视图会把每条 `PhotoActivity` 渲染成活动卡片，进入某个活动后再请求单活动照片接口。

### 查询参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `year` | `number` | 否 | 无 | 按活动年份筛选 |
| `search` | `string` | 否 | 无 | 搜索活动名称和活动简介 |
| `sort` | `string` | 否 | `hot` | `hot`、`new`、`old` 或 `photoCount` |

### 响应字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `data` | `PhotoActivity[]` | 符合筛选条件的活动照片集合 |

### PhotoActivity 结构

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `number` | 活动 ID |
| `activity` | `string` | 活动名称 |
| `description` | `string` | 活动照片简介 |
| `year` | `number` | 活动年份 |
| `hot` | `number` | 活动热度 |
| `sortOrder` | `number` | 活动列表人工排序权重，数字越小越靠前 |
| `photoDir` | `string \| null` | 活动照片目录 |
| `archiveUrl` | `string \| null` | 活动压缩文件 URL，存在同名 `.rar` 时返回 |
| `coverSrc` | `string \| null` | 活动封面原图 URL |
| `coverThumbSrc` | `string \| null` | 活动封面缩略图 URL |
| `photoCount` | `number` | 活动照片数量 |
| `createdAt` | `string | null` | 创建时间 |

活动卡片不使用 icon 字段；“全部活动”视图使用活动第一张照片作为封面。活动列表接口只返回封面和数量，不返回完整照片数组。

活动级下载使用照片目录下的同名压缩文件，不能由前端逐张触发下载。例如 `photoDir` 是 `/uploads/photos/春季运动会/` 时，压缩文件应放在 `/uploads/photos/春季运动会/春季运动会.rar`。只有该文件实际存在时，接口才返回 `archiveUrl`。

### 响应示例

```json
{
  "data": [
    {
      "id": 1,
      "activity": "春季运动会",
      "description": "记录开幕式、接力赛、领奖瞬间和操场看台等运动会现场照片。",
      "year": 2026,
      "hot": 98,
      "sortOrder": 10,
      "coverSrc": "https://images.unsplash.com/photo-1461896836934-ffe607ba8211?auto=format&fit=crop&w=1200&q=85",
      "coverThumbSrc": null,
      "photoCount": 4,
      "createdAt": "2026-05-10T10:00:00"
    }
  ]
}
```

## GET /api/photo-activities/{activity_id}/photos

获取单个活动下的照片。前端进入某个活动详情时调用该接口。

### 响应字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `data` | `PhotoItem[]` | 指定活动下的照片 |

### PhotoItem 结构

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `number` | 照片 ID |
| `title` | `string` | 照片标题 |
| `src` | `string` | 照片 URL |
| `thumbSrc` | `string \| null` | 缩略图 URL；本地 `photoDir` 图片会懒生成 WebP 缩略图，旧数据或生成失败时为空 |
| `sortOrder` | `number` | 活动内排序 |

### 参数错误

`sort` 只允许 `hot`、`new`、`old` 或 `photoCount`。传入其他值会返回 `422 Unprocessable Entity`。

## 管理后台 API

所有管理后台接口都以 `/api/admin` 开头，并且必须携带 `Authorization: Bearer <accessToken>`。只有 `role` 为 `admin` 的用户可以访问。未登录返回 `401 Unauthorized`，普通用户返回 `403 Forbidden`。

### 用户管理

- `GET /api/admin/users`：查询用户列表，支持 `search`、`role`、`isActive`。
- `POST /api/admin/users`：创建用户。字段：`username`、`password`、`displayName`、`role`、`isActive`。
- `PATCH /api/admin/users/{user_id}`：更新用户权限和状态。只允许字段：`role`、`isActive`。

`POST /api/admin/users` 允许管理员创建普通用户或管理员；`role` 只能是 `admin` 或 `user`。

### CAS 项目管理

后台 CAS 项目管理复用前台项目库的信息架构：左侧筛选和分类、右侧项目列表。项目列表支持新建和编辑，不提供删除。项目分类可拖拽排序，排序会同时影响前台 `GET /api/meta` 的分类顺序。

- `GET /api/admin/project-categories`：查询 CAS 项目分类列表，按 `sortOrder` 升序返回。
- `PATCH /api/admin/project-categories/reorder`：批量更新 CAS 项目分类顺序。请求体：`{"items":[{"id":1,"sortOrder":10}]}`。
- `GET /api/admin/projects`：查询后台 CAS 项目列表，支持 `search`、`category`、`year`、`sort`。
- `POST /api/admin/projects`：创建 CAS 项目。
- `PATCH /api/admin/projects/{project_id}`：更新 CAS 项目。

CAS 项目写接口字段包括：`name`、`leader`、`members`、`category`、`year`、`icon`、`description`、`media`、`casCreativity`、`casActivity`、`casService`、`popularity`、`updates`。其中 `media` 和 `updates` 是字符串数组，后端保存为 MySQL JSON；管理员在后台项目详情视图中直接拖拽 `media` 排序，拖动结束后自动保存，保存后的数组顺序就是正式详情页媒体展示顺序。编辑弹窗只修改项目基础信息和动态，正式前台详情页不提供编辑或排序能力。

`sortOrder` 是分类人工排序权重，数字越小越靠前。当前只用于 CAS 项目分类，不控制项目本身排序；项目仍按 `latest` 或 `popular` 排序。

### 资源管理

后台资源管理直接复用前台资源中心的信息架构：顶部筛选条、左侧资源类型/活动筛选、右侧资源卡片或活动照片内容区。普通资源走资源接口；选择 `photos` 活动照片分类时，后台在同一资源管理页面调用活动照片接口，不再提供独立的活动照片导航。

- `GET /api/admin/resource-categories`：查询资源分类列表，按 `sortOrder` 升序返回。
- `PATCH /api/admin/resource-categories/reorder`：批量更新资源分类顺序。请求体：`{"items":[{"id":1,"sortOrder":10}]}`。
- `GET /api/admin/resources`：查询后台资源列表，支持 `search`、`category`、`year`。
- `POST /api/admin/resources`：创建资源。
- `PATCH /api/admin/resources/{resource_id}`：更新资源。
- `DELETE /api/admin/resources/{resource_id}`：删除资源。

资源字段包括：`title`、`description`、`year`、`category`、`label`、`type`、`hot`、`downloads`、`image`、`resourceUrl`。

`sortOrder` 是人工排序权重，数字越小越靠前。当前只用于资源分类和活动列表；普通资源卡片和单张照片卡片不使用人工排序。

### 活动照片管理

- `GET /api/admin/photo-activities`：查询活动列表，支持 `search`、`year`。该接口由后台资源管理中的 `photos` 分类使用。
- `POST /api/admin/photo-activities`：创建活动。字段：`activity`、`description`、`year`、`hot`、`sortOrder`、`photoDir`。
- `PATCH /api/admin/photo-activities/{activity_id}`：更新活动。
- `PATCH /api/admin/photo-activities/reorder`：批量更新活动列表顺序。请求体：`{"items":[{"id":1,"sortOrder":10}]}`。
- `DELETE /api/admin/photo-activities/{activity_id}`：删除活动，活动下照片记录会被外键级联删除。
- `GET /api/admin/photo-activities/{activity_id}/photos`：查询活动下的照片。
- `POST /api/admin/photo-activities/{activity_id}/photos`：新增照片。字段：`title`、`src`、`sortOrder`。
- `PATCH /api/admin/photos/{photo_id}`：更新照片。
- `DELETE /api/admin/photos/{photo_id}`：删除照片。

后台活动照片 v1 推荐使用目录模型：`photoDir` 保存 `public/` 下的目录 URL，例如 `/uploads/sports-2026/`。后台资源管理只编辑活动记录和照片目录，不再提供单张照片编辑入口；旧的单张照片接口保留兼容，不作为主要管理方式。

公开接口 `GET /api/photo-activities` 会优先扫描 `photoDir` 指向的目录生成照片列表；未配置目录时继续读取旧 `photo_items` 数据。目录扫描支持 `jpg`、`jpeg`、`png`、`webp`、`gif`，标题使用文件名，按文件名升序排列。

目录扫描结果会按 `PHOTO_DIR_CACHE_MINUTES` 做后端进程内缓存，单位是分钟，默认 5。缓存按活动目录独立保存；单活动照片接口命中缓存时直接复用照片列表，不重新扫描目录，也不重复检查缩略图；缓存过期后的下一次访问会重新扫描并为新增或更新的照片生成缩略图。设置为 `0` 可关闭缓存。

### 文件管理与上传

`GET /api/admin/files/tree?path=` 浏览 `public/` 目录下的文件和文件夹。`path` 是相对 `public/` 的目录路径，例如 `uploads`。返回项包含 `name`、`path`、`url`、`type`、`size`、`updatedAt`。

`POST /api/admin/uploads` 使用 `multipart/form-data`。字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `file` | `file` | 是 | 上传文件 |
| `targetPath` | `string` | 否 | 相对 `public/` 的目标目录，例如 `uploads/yearbook` |

允许扩展名：`jpg`、`jpeg`、`png`、`webp`、`gif`、`pdf`、`doc`、`docx`、`ppt`、`pptx`、`xls`、`xlsx`、`zip`、`rar`。单文件最大 50MB。普通文件上传后使用随机文件名保存；`.rar` 压缩文件保留原文件名，方便活动照片目录使用同名压缩文件。

成功响应：

```json
{
  "url": "/uploads/yearbook/example.pdf",
  "filename": "example.pdf",
  "size": 12345,
  "targetPath": "uploads/yearbook"
}
```

路径安全限制：`path` 和 `targetPath` 必须解析后仍位于 `public/` 内；不允许 `..` 和以 `/` 开头的绝对路径。

资源和照片编辑接口只保存 URL。上传文件请先到后台“文件管理”栏目完成，再在资源或照片编辑中手动填写地址，或通过“浏览”选择已有文件/文件夹。

### 数据库查看器

数据库查看器只允许访问白名单表：`users`、`projects`、`project_categories`、`resource_categories`、`resources`、`photo_activities`、`photo_items`。不开放任意 SQL。

- `GET /api/admin/db/tables`：返回可访问表列表。
- `GET /api/admin/db/tables/{table}/schema`：返回字段结构。
- `GET /api/admin/db/tables/{table}/rows?page=1&pageSize=50`：分页查询数据。
- `POST /api/admin/db/tables/{table}/rows`：新增记录。
- `PATCH /api/admin/db/tables/{table}/rows/{id}`：更新记录。
- `DELETE /api/admin/db/tables/{table}/rows/{id}`：删除记录。

限制：`users.password_hash` 不返回、不允许编辑；`id`、`created_at`、`updated_at` 为只读字段；表名和字段名必须来自白名单或数据库结构。`users` 表新增记录请使用用户管理接口，不通过数据库查看器创建。
