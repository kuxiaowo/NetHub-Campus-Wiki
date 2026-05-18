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
| `icon` | `string` | 项目图标或 emoji |
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
      "icon": "🗺️",
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
    "icon": "🗺️",
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
| `years` | `number[]` | 资源年份 |
| `photoYears` | `number[]` | 照片活动年份 |

## GET /api/resources

获取资源中心普通资源列表，支持分类、年份、关键词和排序。

### 查询参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `category` | `string` | 否 | 无 | 按资源分类筛选，例如 `yearbook`、`photos`、`other` |
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

### 参数错误

`sort` 只允许 `hot`、`new`、`old` 或 `download`。传入其他值会返回 `422 Unprocessable Entity`。

## GET /api/photo-activities

获取活动照片列表，每个活动包含自己的照片数组。

### 查询参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `year` | `number` | 否 | 无 | 按活动年份筛选 |
| `search` | `string` | 否 | 无 | 搜索活动名称 |
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
| `year` | `number` | 活动年份 |
| `hot` | `number` | 活动热度 |
| `images` | `PhotoItem[]` | 活动照片 |
| `createdAt` | `string | null` | 创建时间 |

### PhotoItem 结构

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `number` | 照片 ID |
| `title` | `string` | 照片标题 |
| `src` | `string` | 照片 URL |
| `sortOrder` | `number` | 活动内排序 |

### 参数错误

`sort` 只允许 `hot`、`new`、`old` 或 `photoCount`。传入其他值会返回 `422 Unprocessable Entity`。
