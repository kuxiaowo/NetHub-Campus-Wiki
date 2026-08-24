# Campus Wiki API 文档

基础地址：

```text
http://127.0.0.1:3100
```

所有业务接口都以 `/api` 开头，响应格式为 JSON。前端从运行时配置 `window.CAMPUS_WIKI_CONFIG` 读取 API 前缀；使用 `frontend_server.py` 时，该配置由 `.env` 中的 `FRONTEND_API_BASE_URL` 动态生成：

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
- 查看与下载权限：资源列表、Yearbook 阅读器数据、活动照片列表和图片查看保持公开；实际下载普通资源文件、Yearbook PDF、活动压缩包或单张照片时必须登录。前端未登录点击下载会弹出 `抱歉，需要登陆` 并阻止下载请求。

## 用户结构

认证接口中的 `User` 使用以下结构：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `number` | 用户 ID |
| `username` | `string` | 昵称/登录用户名 |
| `displayName` | `string \| null` | 姓名 |
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
| `username` | `string` | 是 | 昵称/登录用户名，3-32 位，只允许字母、数字和下划线 |
| `password` | `string` | 是 | 至少 8 位 |
| `displayName` | `string` | 否 | 姓名 |

### 成功响应

返回 `User`。

### 常见错误

- `409 Conflict`：昵称已存在。
- `422 Unprocessable Entity`：昵称或密码格式不符合要求。

## POST /api/auth/login

使用昵称和密码登录，返回 Bearer Token。

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

- `401 Unauthorized`：昵称或密码错误。
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

## PATCH /api/auth/me

修改当前登录用户的昵称。昵称同时作为登录用户名使用。

### 请求示例

```bash
curl -X PATCH http://127.0.0.1:3100/api/auth/me \
  -H "Authorization: Bearer <accessToken>" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"student02\"}"
```

### 请求字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `username` | `string` | 是 | 新昵称/登录用户名，3-32 位，只允许字母、数字和下划线 |

### 成功响应

返回更新后的 `User`，前端应同步刷新本地保存的当前用户信息。

### 常见错误

- `401 Unauthorized`：缺少 token、token 无效或 token 已过期。
- `403 Forbidden`：账号已被禁用。
- `409 Conflict`：昵称已存在。
- `422 Unprocessable Entity`：昵称格式不符合要求。

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

分页获取已发布公告。首页使用 `pageSize=3`，全部公告页使用搜索和分页。

查询参数：`page`、`pageSize`、`search`。

### 请求示例

```bash
curl http://127.0.0.1:3100/api/announcements
```

### 响应字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `data` | `object[]` | 公告摘要列表 |
| `total` | `number` | 公告总数 |
| `hasMore` | `boolean` | 是否还有下一页 |

### 响应示例

```json
{
  "data": [{
    "id": 1,
    "title": "CAS 项目库原型上线",
    "summary": "欢迎提交你的项目资料。",
    "isPinned": true,
    "viewCount": 12,
    "commentCount": 3,
    "publishedAt": "2026-07-29 10:00:00"
  }],
  "page": 1,
  "pageSize": 10,
  "total": 1,
  "hasMore": false
}
```

## GET /api/announcements/{announcement_id}

读取单条已发布公告的正文、作者、浏览量和留言数。默认每次读取会增加一次浏览量；内部检查可传 `track=false`。

## 留言接口

公告、项目和普通资源使用同一套两级留言接口。读取公开，写操作需要 Bearer Token。

- `GET /api/comments?targetType=announcement|project|resource&targetId=1&sort=hot|latest&page=1&pageSize=10`：分页读取主留言及其全部回复。
- `GET /api/comments/{comment_id}/context`：读取指定可见留言所属的完整回复线程，用于通知深链接定位。
- `POST /api/comments`：发布留言；请求体为 `targetType`、`targetId`、`content`，回复时增加 `parentId`。
- `DELETE /api/comments/{comment_id}`：软删除自己的留言；管理员也可删除。
- `POST|DELETE /api/comments/{comment_id}/like`：点赞或取消点赞。
- `POST /api/comments/{comment_id}/reports`：举报他人留言，请求体为 `{"reason":"..."}`。

回复始终归入两级展示：回复某条回复时，`parentId` 指向被回复留言，`rootId` 仍指向主留言。删除主留言只清空正文，回复关系保留。双方任一方存在黑名单关系时，回复会返回 `403`。

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
| `leader` | `string` | 负责人姓名摘要；成员尚未设置时为空字符串 |
| `members` | `string` | 兼容旧客户端的成员姓名摘要 |
| `memberList` | `ProjectMember[]` | 结构化成员；项目详情接口返回完整数据，列表接口可为空数组 |
| `category` | `string` | 项目分类 |
| `year` | `number` | 项目年份 |
| `icon` | `string` | 项目图标图片 URL |
| `description` | `string` | 项目简介 |
| `media` | `string[]` | 旧版项目级媒体兼容字段；新项目固定为空，后台不可编辑且前台不展示 |
| `cas` | `object` | CAS 三项标记 |
| `cas.creativity` | `boolean` | 是否包含 Creativity |
| `cas.activity` | `boolean` | 是否包含 Activity |
| `cas.service` | `boolean` | 是否包含 Service |
| `popularity` | `number` | 热度分 |
| `updates` | `ProjectUpdate[] | string[]` | 项目动态；旧数据可能仍为纯文字字符串数组 |
| `createdAt` | `string | null` | 创建时间 |
| `updatedAt` | `string | null` | 更新时间 |

`ProjectUpdate` 结构：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `content` | `string` | 本条动态文字，可为空 |
| `images` | `string[]` | 只属于本条动态的照片 URL，可为空数组 |

`ProjectMember` 包含 `personId`、`name`、`role`、`sortOrder`、账号绑定状态以及可选的 `contactType`、`contactValue`。`role` 为 `leader` 或 `member`；`contactType` 为 `wechat`、`phone`、`email`、`other` 之一。联系方式按“项目—成员”关系保存，同一人员在不同项目中可使用不同联系方式。

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
      "media": [],
      "cas": {
        "creativity": true,
        "activity": true,
        "service": true
      },
      "popularity": 96,
      "updates": [
        {
          "content": "完成第一版传感器数据模拟器",
          "images": ["https://picsum.photos/seed/noise-map/900/520"]
        }
      ],
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
    "memberList": [
      {
        "personId": 1,
        "name": "李明",
        "role": "leader",
        "registered": false,
        "sortOrder": 0,
        "contactType": "wechat",
        "contactValue": "liming-cas"
      }
    ],
    "category": "科技创新",
    "year": 2026,
    "icon": "https://picsum.photos/seed/noise-map-icon/300/300",
    "description": "使用传感器采集校园不同地点的噪音数据。",
    "media": [],
    "cas": {
      "creativity": true,
      "activity": true,
      "service": true
    },
    "popularity": 96,
    "updates": [
      {
        "content": "完成第一版传感器数据模拟器",
        "images": ["https://picsum.photos/seed/noise-map/900/520"]
      }
    ],
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

获取资源中心筛选器需要的固定资源类型、资源年份和照片活动年份。固定类型为 `yearbook`、`photos`、`teacher` 和 `other`，由代码定义，不依赖数据库内容。

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
| `categories[].sortOrder` | `number` | 代码中固定的显示顺序权重 |
| `years` | `number[]` | 资源年份 |
| `photoYears` | `number[]` | 照片活动年份 |

资源中心前端使用同一组顶部筛选控件服务不同分类：选择“全部资源”时会同时请求 `/api/resources` 和 `/api/photo-activities`，把普通资源和所有活动照片活动混合展示，并过滤旧的 `resources.category = "photos"` 入口；选择普通资源分类时只请求 `/api/resources`；选择 `photos` 活动照片分类时请求 `/api/photo-activities` 获取活动列表，进入某个活动后再请求 `/api/photo-activities/{activity_id}/photos` 获取照片。

## GET /api/resources

获取资源中心普通资源列表，支持分类、年份、关键词和排序。

### 查询参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `category` | `string` | 否 | 无 | 按资源分类筛选，可用值为 `yearbook`、`teacher`、`other`；活动照片使用 `/api/photo-activities` |
| `year` | `number` | 否 | 无 | 按资源年份筛选 |
| `search` | `string` | 否 | 无 | 搜索资源标题、简介和分类展示名 |
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
| `hot` | `number` | 热度 |
| `downloads` | `number` | 下载次数 |
| `image` | `string` | 卡片缩略图或详情封面 URL；本地 `teacher` 视频会动态返回首帧缩略图，外部视频无法生成时为空字符串 |
| `resourceUrl` | `string` | 资源访问、下载或浏览器可直接播放的视频 URL |
| `createdAt` | `string | null` | 创建时间 |
| `updatedAt` | `string | null` | 更新时间 |

资源中心卡片不再使用 icon 字段，展示缩略图，文字只显示标题和年份，点击整张卡片进入资源详情页。普通资源的 `image` 同时用于卡片和详情页；本地 `teacher` 视频的 `image` 是动态生成的首帧 WebP，列表不内嵌视频，详情页才使用 `resourceUrl` 渲染播放器。

### 参数错误

`sort` 只允许 `hot`、`new`、`old` 或 `download`。传入其他值会返回 `422 Unprocessable Entity`。

## GET /api/resources/{resource_id}

获取单个资源详情。前台点击资源卡片进入详情页时会调用本接口并计入资源热度。热度使用通用节流逻辑，同一登录账户对同一资源 5 秒内只增加一次。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `track` | `boolean` | 否 | `true` | 是否计入前台浏览热度；后台读取时应传 `false` |

成功响应为 `{ "data": Resource }`；资源不存在时返回 `404 Not Found`。

## GET /api/resources/{resource_id}/yearbook

读取单个 Yearbook 资源的双页阅读器数据。该接口只支持 `resources.category = "yearbook"` 的资源，并要求 `resourceUrl` 指向 `public/` 下的目录，例如 `/uploads/yearbook/2026/`。

前台默认会把本接口调用计入资源热度；热度使用通用节流逻辑，同一登录账户对同一对象 5 秒内只会增加一次。后台预览应传 `track=false`，例如 `/api/resources/1/yearbook?track=false`。

该接口不要求登录，未登录用户也可以查看 Yearbook 页面图片；只有点击 PDF 下载或单页图片下载时才要求登录。

目录约定：

- 页面文件扫描 `.jpg`、`.jpeg`、`.png`、`.webp`、`.gif`，按文件名自然升序排列。
- 封面不单独维护，资源详情页和资源列表卡片均使用目录中排序第一张图片的缩略图；卡片文字只显示标题和年份。
- PDF 下载文件扫描 `.pdf`，如果有多个，使用文件名自然升序的第一个。
- 推荐文件名：`001.png`、`002.png`、`003.png`、`yearbook.pdf`。

### 响应字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `data.resource` | `Resource` | Yearbook 资源记录 |
| `data.pages` | `YearbookPage[]` | 图片页面列表 |
| `data.pages[].index` | `number` | 页面序号，从 1 开始 |
| `data.pages[].title` | `string` | 页面文件名，不含扩展名 |
| `data.pages[].src` | `string` | 图片页面 URL |
| `data.pages[].thumbSrc` | `string \| null` | WebP 缩略图 URL；后端会懒生成到页面目录下的 `.thumbs/`，生成失败时为 `null` |
| `data.pdfUrl` | `string \| null` | PDF 下载 URL；目录内没有 PDF 时为 `null` |

### 常见错误

- `404 Not Found`：资源不存在，或资源不是 `yearbook` 分类。
- `422 Unprocessable Entity`：`resourceUrl` 不是 `public/` 下的目录、目录不存在，或目录内没有图片页面。

## POST /api/resources/{resource_id}/download

给资源下载数加一，并返回更新后的资源。下载数不做 5 秒节流，前台点击普通资源链接、Yearbook PDF 下载或 Yearbook 单页图片下载时调用；后台预览和后台下载不调用，避免管理员操作影响公开统计。

该接口必须登录，需携带 `Authorization: Bearer <accessToken>`。未登录返回 `401 Unauthorized`；前端未登录点击下载时会先弹出 `抱歉，需要登陆`，不会发起下载统计请求。

### 响应字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `data` | `Resource` | 更新下载数后的资源 |

### 常见错误

- `401 Unauthorized`：未登录、token 无效或 token 已过期。
- `404 Not Found`：资源不存在。

## GET /api/photo-activities

获取活动照片活动列表。资源中心选择“活动照片”分类时使用此接口；“全部活动”视图会把每条 `PhotoActivity` 渲染成使用第一张照片缩略图、文字只含标题和年份的活动卡片，点击整张卡片进入活动后再请求单活动照片接口。

### 查询参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `year` | `number` | 否 | 无 | 按活动年份筛选 |
| `search` | `string` | 否 | 无 | 搜索活动名称和活动简介 |
| `sort` | `string` | 否 | `hot` | `hot`、`new`、`old`、`photoCount` 或 `download` |

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
| `downloads` | `number` | 活动下载次数 |
| `sortOrder` | `number` | 活动列表人工排序权重，数字越小越靠前 |
| `photoDir` | `string \| null` | 活动照片目录 |
| `archiveUrl` | `string \| null` | 活动压缩文件 URL，存在同名 `.rar` 时返回 |
| `coverSrc` | `string \| null` | 活动封面原图 URL |
| `coverThumbSrc` | `string \| null` | 活动封面缩略图 URL |
| `photoCount` | `number` | 活动照片数量 |
| `createdAt` | `string | null` | 创建时间 |

活动卡片不使用 icon 字段，使用按文件名自然排序的第一张照片作为缩略图，文字只显示标题和年份。活动列表接口只返回封面和数量，不返回完整照片数组。

活动级整包下载使用照片目录下的同名压缩文件。例如 `photoDir` 是 `/uploads/photos/春季运动会/` 时，压缩文件应放在 `/uploads/photos/春季运动会/春季运动会.rar`。只有该文件实际存在时，接口才返回 `archiveUrl`。前台点击活动整包下载或在照片放大弹窗中下载单张照片，都会让活动级 `downloads` 加 1。

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
      "downloads": 24,
      "sortOrder": 10,
      "coverSrc": "https://images.unsplash.com/photo-1461896836934-ffe607ba8211?auto=format&fit=crop&w=1200&q=85",
      "coverThumbSrc": null,
      "photoCount": 4,
      "createdAt": "2026-05-10T10:00:00"
    }
  ]
}
```

## POST /api/photo-activities/{activity_id}/download

记录一次活动照片下载，并返回更新后的活动摘要。该接口统计活动级下载量，前台下载整包压缩文件和下载单张放大照片都会调用它。

该接口必须登录，需携带 `Authorization: Bearer <accessToken>`。未登录返回 `401 Unauthorized`；前端未登录点击下载时会先弹出 `抱歉，需要登陆`，不会发起下载统计请求。

### 响应字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `data` | `PhotoActivity` | 更新下载数后的活动照片摘要 |

## GET /api/photo-activities/{activity_id}/photos

获取单个活动下的照片。前端进入某个活动详情时调用该接口。前台默认会把本接口调用计入活动热度；热度使用通用节流逻辑，同一登录账户对同一活动 5 秒内只会增加一次。后台预览应传 `track=false`，例如 `/api/photo-activities/1/photos?track=false`。

该接口不要求登录，未登录用户也可以查看照片列表和放大预览；只有点击活动整包下载或单张照片下载时才要求登录。

### 查询参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `track` | `boolean` | 否 | `true` | 是否计入前台浏览热度 |

### 响应字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `data` | `PhotoItem[]` | 指定活动下的照片 |
| `activity` | `PhotoActivity \| null` | 更新热度后的活动摘要 |

### PhotoItem 结构

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `number` | 照片 ID |
| `title` | `string` | 照片标题 |
| `src` | `string` | 照片 URL |
| `thumbSrc` | `string \| null` | 缩略图 URL；本地 `photoDir` 图片会懒生成 WebP 缩略图，旧数据或生成失败时为空 |
| `sortOrder` | `number` | 活动内排序 |

### 参数错误

`sort` 只允许 `hot`、`new`、`old`、`photoCount` 或 `download`。传入其他值会返回 `422 Unprocessable Entity`。

## GET /api/files/{file_path}

从 `public/` 目录读取文件并作为附件返回。该接口用于受登录保护的下载，不用于普通图片查看。前端在下载普通资源文件、Yearbook PDF、活动压缩包或单张照片时，会把本地 `public/` URL 转换为 `/api/files/...` 下载 URL。

### 鉴权

必须登录。接口支持两种传递 token 的方式：

- `Authorization: Bearer <accessToken>`：适合 `fetch` 或 API 客户端。
- `?token=<accessToken>`：适合浏览器 `<a download>` 这类无法附加请求头的下载链接。

未登录、token 无效或 token 已过期时返回 `401 Unauthorized`。前端未登录点击下载时会先弹出 `抱歉，需要登陆`，不会跳转到该接口。

### 路径安全

`file_path` 是相对 `public/` 的文件路径，例如 `uploads/yearbook/2026/yearbook.pdf` 或 `Photos/activity/001.jpg`。后端会拒绝空路径、绝对路径、Windows 盘符路径和包含 `..` 的路径；解析后的文件必须仍位于 `public/` 下。

### 响应

成功时返回文件内容，并设置 `Content-Disposition: attachment` 和 `Cache-Control: private, no-store, max-age=0`。

### 常见错误

- `401 Unauthorized`：未登录、token 无效或 token 已过期。
- `404 Not Found`：文件不存在，或路径不在允许范围内。

## 用户资料与关系

以下用户关系接口需 Bearer Token；人员档案详情可公开读取：

- `GET /api/users?search=`：搜索可私信的启用用户。
- `GET /api/users/{user_id}`：用户公开资料、关注关系和已关联 CAS 项目。
- `PATCH /api/users/me/profile`：修改 `displayName`、`avatarUrl`、`bio`、`messagingPermission`。
- `POST|DELETE /api/users/{user_id}/follow`：关注或取消关注。
- `POST|DELETE /api/users/{user_id}/block`：拉黑或解除拉黑；拉黑会移除双方关注关系。
- `GET /api/people/{person_id}`：读取人员档案和参与项目。

普通用户不能申请或修改人员档案的账号绑定。绑定只能由管理员在 CAS 项目详情的成员区域操作。

`messagingPermission` 可取 `everyone`、`following`、`mutual`、`nobody`。

## 私信接口

- `POST /api/conversations`：使用 `targetUserId` 打开或创建一对一会话。
- `GET /api/conversations`：读取当前用户的所有可见会话。
- `GET /api/conversations/{id}/messages`：分页读取聊天记录。
- `POST /api/conversations/{id}/messages`：发送 `text` 或 `project` 消息。
- `POST /api/conversations/{id}/read`：更新当前用户的已读位置。
- `DELETE /api/conversations/{id}`：仅为当前用户隐藏会话，不删除双方消息。
- `POST /api/messages/{id}/recall`：发送者在两分钟内撤回消息。
- `POST /api/messages/{id}/reports`：举报消息。
- `GET /api/messages/unread-count`：读取私信未读数。
- `POST /api/messages/stream-ticket`：创建 60 秒内有效且只能使用一次的实时连接凭证。
- `WS /api/messages/ws?ticket=...`：接收 `message`、`read`、`recall` 实时事件。

对方尚未回复、且当前没有关注发送者时，同一发送者对该用户每个北京时间自然日最多发送一条消息；超限返回 `429`。对方回复过一次后永久解除该限制，对方当前关注发送者时也不受限制。所有权限、黑名单和频率限制均由后端校验。

## 留言互动通知接口

- `GET /api/comment-notifications?kind=reply|like&page=1&pageSize=20`：分页读取回复或收到的赞，并返回本次分类快照的 `latestId`。
- `POST /api/comment-notifications/read`：使用 `kind` 和 `throughId` 将该分类边界以内的通知标为已读。
- `GET /api/message-center/unread-count`：返回 `{total, messages, replies, likes}`，供消息中心侧栏和全站消息角标使用。

通知仅记录接口上线后的新互动，不回填历史。取消点赞和删除留言不会删除通知；重新点赞会复用原通知、更新时间并重新标记未读。自我回复和给自己的留言点赞不产生通知。

## 管理后台 API

所有管理后台接口都以 `/api/admin` 开头，并且必须携带 `Authorization: Bearer <accessToken>`。只有 `role` 为 `admin` 的用户可以访问。未登录返回 `401 Unauthorized`，普通用户返回 `403 Forbidden`。

### JSON 数据导入/导出

JSON 迁移覆盖 CAS 项目（含成员联系方式与动态）、普通资源、活动照片及其旧版单张照片记录。路径字段只保存 `public/` 下的 URL（如 `/CAS/ride/icon.png`）或 `http(s)` URL，不传输图片、PDF、视频或压缩包本身。`yearbook.resourceUrl` 和活动的 `photoDir` 必须使用 `public/` 站内目录；图片、视频及普通资源地址可使用外部 `http(s)` URL。数据库 ID、用户账号绑定及创建/更新时间不会导出。

- `GET /api/admin/data-export`：整体导出全部项目和资源。
- `GET /api/admin/data-template`：下载包含三类数据示例的模板。
- `GET /api/admin/projects/{project_id}/export`：单独导出一个 CAS 项目。
- `GET /api/admin/resources/{resource_id}/export`：单独导出一个普通资源。
- `GET /api/admin/photo-activities/{activity_id}/export`：单独导出一个照片活动。
- `POST /api/admin/data-import/preview`：只验证并返回数量汇总和路径预警，不写数据库。
- `POST /api/admin/data-import?confirmWarnings=true`：整批写入；存在路径预警时必须传 `confirmWarnings=true`。

导入文件使用统一信封，因此可以把单个项目/资源放在对应数组中，也可以一次放入多个不同类型的数据：

```json
{
  "format": "nethub-campus-wiki-data",
  "version": 1,
  "exportedAt": "2026-08-24T12:00:00Z",
  "projects": [],
  "resources": [],
  "photoActivities": []
}
```

预检成功返回 `summary`（项目、成员、动态、普通资源、照片活动和照片条目数量）及 `warnings`。字段错误、未知字段或格式版本不支持时返回 `422`，且不写入任何记录；站内路径不存在或类型不符时预检仍成功，但正式导入未确认预警会返回 `409`。每次成功导入都创建新记录，重复导入同一文件会继续新增，不做去重或覆盖。整批导入在一个数据库事务内执行，数据库写入失败会全部回滚。

### 用户管理

- `GET /api/admin/users`：查询用户列表，支持 `search`、`role`、`isActive`。
- `POST /api/admin/users`：创建用户。字段：`username`、`password`、`displayName`、`role`、`isActive`。
- `PATCH /api/admin/users/{user_id}`：更新用户姓名、权限和状态。只允许字段：`displayName`、`role`、`isActive`。

`username` 是昵称/登录用户名，`displayName` 是姓名。`POST /api/admin/users` 允许管理员创建普通用户或管理员；`role` 只能是 `admin` 或 `user`。`PATCH /api/admin/users/{user_id}` 中 `displayName` 传空字符串时保存为 `NULL`。

### 公告与留言

- `GET /api/admin/announcements`：读取全部公告，包括草稿和归档。
- `POST /api/admin/announcements`：创建公告。字段为 `title`、`summary`、`content`、`status`、`isPinned`。
- `PATCH /api/admin/announcements/{announcement_id}`：编辑公告或切换发布状态。
- `DELETE /api/admin/announcements/{announcement_id}`：归档公告，不物理删除公告和留言。
- `GET /api/admin/comment-reports?status=pending`：读取留言举报。
- `PATCH /api/admin/comment-reports/{report_id}`：以 `resolved` 或 `dismissed` 处理；`hideComment=true` 时同时隐藏被举报留言。
- `GET /api/admin/message-reports?status=pending`：读取私信举报。
- `PATCH /api/admin/message-reports/{report_id}`：以 `resolved` 或 `dismissed` 处理举报。

### CAS 项目管理

后台 CAS 项目管理复用前台项目库的信息架构：左侧筛选和分类、右侧项目列表。首次创建只录入基本信息；创建成功后从项目列表进入后台详情，分别管理基本信息、成员及联系方式和动态。项目不再提供总体照片/视频区，每条动态单独维护自己的照片。当前不提供删除。项目分类可拖拽排序，排序会同时影响前台 `GET /api/meta` 的分类顺序。

- `GET /api/admin/project-categories`：查询 CAS 项目分类列表，按 `sortOrder` 升序返回。
- `PATCH /api/admin/project-categories/reorder`：批量更新 CAS 项目分类顺序。请求体：`{"items":[{"id":1,"sortOrder":10}]}`。
- `GET /api/admin/projects`：查询后台 CAS 项目列表，支持 `search`、`category`、`year`、`sort`。
- `GET /api/admin/projects/{project_id}`：读取单个项目及完整 `memberList`，用于后台详情管理。
- `POST /api/admin/projects`：创建 CAS 项目。只接受 `name`、`category`、`year`、`icon`、`description`、`casCreativity`、`casActivity`、`casService`；新项目的成员、负责人、媒体和动态均为空。
- `PATCH /api/admin/projects/{project_id}`：更新项目基本信息，或在创建后更新 `updates`、`popularity`；不接受 `leader`、旧的 `members` 文本字段或项目级 `media`。负责人只能通过结构化成员接口确定。
- `PATCH /api/admin/projects/{project_id}/members`：整体替换结构化成员列表。请求体为 `{"members":[{"personId":1,"name":"李明","role":"leader","contactType":"wechat","contactValue":"liming-cas"}]}`；新成员可省略 `personId`。
- `PATCH /api/admin/projects/{project_id}/members/{person_id}/binding`：把该项目成员绑定到启用的站内用户，传 `{"userId":12}`；传 `{"userId":null}` 解除绑定。只有管理员可调用，且 `person_id` 必须属于指定项目。

项目刚创建时允许成员列表为空。保存成员时列表不能为空，负责人未知时可以全部先标为 `member`；确认后最多只能有一名 `leader`，后端会据此同步项目的负责人姓名摘要。联系方式可以整组留空；一旦填写，就必须同时提供 `contactType` 和 `contactValue`。成员账号只能在后台项目详情中绑定，一个账号最多绑定一个人员档案。`updates` 请求是 `ProjectUpdate[]`，例如 `[{"content":"完成第一次骑行","images":["/CAS/ride/001.jpg"]}]`；每条动态可以只有文字、只有照片或同时包含二者。正式前台详情页只负责展示，不提供认领或绑定能力。

`sortOrder` 是分类人工排序权重，数字越小越靠前。当前只用于 CAS 项目分类，不控制项目本身排序；项目仍按 `latest` 或 `popular` 排序。

### 资源管理

后台资源管理直接复用前台资源中心的信息架构和 `public/js/resource-ui.js` 渲染模块：顶部筛选条、左侧资源类型/活动筛选、右侧资源卡片或活动照片内容区，以及资源卡片、活动卡片和排序逻辑均与前台共用。后台只在共享卡片上叠加“编辑”等管理入口；点击卡片主体会用 `preview=admin` 打开正式详情页，详情请求传 `track=false`，不增加公开热度。普通资源走资源接口；选择 `photos` 活动照片分类时，后台在同一资源管理页面调用活动照片接口，不再提供独立的活动照片导航。

- `GET /api/admin/resource-categories`：查询代码中固定的资源类型列表。
- `PATCH /api/admin/resource-categories/reorder`：保留用于兼容旧客户端，但固定类型不可重排，返回 `409 Conflict`。
- `GET /api/admin/resources`：查询后台资源列表，支持 `search`、`category`、`year`。
- `POST /api/admin/resources`：创建资源。
- `PATCH /api/admin/resources/{resource_id}`：更新资源。
- `DELETE /api/admin/resources/{resource_id}`：删除资源。

资源字段包括：`title`、`description`、`year`、`category`、`label`、`hot`、`downloads`、`image`、`resourceUrl`。其中 `hot` 是只读统计字段：创建时固定为 `0`，后台创建和编辑接口均不接受人工设置。

创建 `teacher` 分类资源时，`title`、`description`、`year` 和 `resourceUrl` 必填；后端将 `label` 固定为“老师驾到”、数据库中的 `image` 固定为空字符串，并让热度和下载数使用默认值。公开接口会为 `public/` 下的本地视频动态补充首帧缩略图 URL。视频 URL 必须指向浏览器可直接播放的文件或直链，而不是视频平台的普通页面地址。

活动的 `sortOrder` 是人工排序权重，数字越小越靠前；固定资源类型的顺序由代码定义。普通资源卡片和单张照片卡片不使用人工排序。

### 活动照片管理

- `GET /api/admin/photo-activities`：查询活动列表，支持 `search`、`year`。该接口由后台资源管理中的 `photos` 分类使用。
- `POST /api/admin/photo-activities`：创建活动。字段：`activity`、`description`、`year`、`sortOrder`、`photoDir`；热度固定从 `0` 开始。
- `PATCH /api/admin/photo-activities/{activity_id}`：更新活动。
- `PATCH /api/admin/photo-activities/reorder`：批量更新活动列表顺序。请求体：`{"items":[{"id":1,"sortOrder":10}]}`。
- `DELETE /api/admin/photo-activities/{activity_id}`：删除活动，活动下照片记录会被外键级联删除。
- `GET /api/admin/photo-activities/{activity_id}/photos`：查询活动下的照片。
- `POST /api/admin/photo-activities/{activity_id}/photos`：新增照片。字段：`title`、`src`、`sortOrder`。
- `PATCH /api/admin/photos/{photo_id}`：更新照片。
- `DELETE /api/admin/photos/{photo_id}`：删除照片。

后台活动照片 v1 推荐使用目录模型：`photoDir` 保存 `public/` 下的目录 URL，例如 `/uploads/sports-2026/`。后台资源管理只编辑活动记录和照片目录，不再提供单张照片编辑入口；旧的单张照片接口保留兼容，不作为主要管理方式。

活动的 `hot` 同样是只读统计字段，进入活动照片详情后自动增加；后台创建和编辑接口均不接受人工设置。

公开接口 `GET /api/photo-activities` 会优先扫描 `photoDir` 指向的目录生成照片列表；未配置目录时继续读取旧 `photo_items` 数据。目录扫描支持 `jpg`、`jpeg`、`png`、`webp`、`gif`，标题使用文件名，按文件名自然升序排列。

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

上传到 `public/` 的图片文件可直接用于公开查看。PDF、压缩包和 Office 文档等下载型文件不应依赖前端静态直连；前端下载时会把它们转换到 `GET /api/files/{file_path}`，由后端校验登录后返回附件。
