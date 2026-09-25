# nethub-wiki-media-gateway

私有 R2 bucket `nethub-wiki-media` 和 `nethub-accounts-avatars` 的 HTTP 网关。浏览器只可读取公开图片；管理操作必须由已完成登录、权限、CSRF、类型和大小检查的 Python 后端签名发起。两个 bucket 使用不同的路由、密钥和访问策略。

## 路由

- `GET|HEAD /media/{key}`：公开图片，默认缓存一天，支持单段 `Range`、`If-Range`、`If-None-Match`；响应 MIME 按扩展名白名单强制设置，不信任历史对象元数据。
- `GET|HEAD /download/{key}?expires={unix}&sig={hex}`：短时受保护下载。
- `PUT|HEAD|DELETE /internal/object/{key}`：不覆盖上传、元数据读取、删除。`HEAD` 通过 `Content-Length`、`ETag`、`Content-Type`、`X-Media-Uploaded` 与可选的 `X-Media-SHA256` 返回元数据，不返回响应体。
- `GET|HEAD /accounts/media/avatars/{sub}/{filename}.webp` 及 `PUT|HEAD|DELETE /accounts/internal/object/avatars/{sub}/{filename}.webp`：Accounts 头像专用路由。使用独立的 `nethub-accounts-avatars` R2 binding 和 `ACCOUNTS_AVATAR_HMAC_SECRET`，只接受 UUID 用户目录、24 位十六进制文件名和 WebP，上传限制为 256 KiB。签名请求头沿用 `X-Media-*`，签名目标为去掉 `/accounts` 后的 `/internal/object/...`。
- `GET /internal/list?prefix=...&cursor=...&limit=...`：游标列表，`limit` 为 1–100；`prefix` 必须包含已配置根前缀后的 `/`，不允许从相似的同级前缀开始列举。
- `POST /internal/multipart/{key}`：创建分片上传；可用 `X-Media-Content-Type` 指定类型。
- `PUT /internal/multipart/{key}/part/{1..10000}?uploadId=...`：上传分片。
- `POST /internal/multipart/{key}?uploadId=...`：以 JSON `{"parts":[{"partNumber":1,"etag":"..."}]}` 完成。
- `DELETE /internal/multipart/{key}?uploadId=...`：终止并回滚未完成上传。

对象键按 UTF-8 NFC 规范化，逐段 RFC 3986 编码。空段、`.`、`..`、反斜杠、控制字符、残留 `%`、编码后的路径分隔符、超长键、未配置前缀和扩展名均被拒绝。视频扩展名未列入 Wiki 上传白名单，因此视频本体不能通过该 Worker 写入 R2。

Yearbook 固定使用 `yearbook-pages/`（公开页面原图）、`yearbook-pdfs/`（仅签名下载）
和 `thumbnails/yearbook/`（公开标准 WebP 缩略图）。旧前缀 `yearbook/`、
`yearbook-thumbnails/` 不允许访问，Worker 不提供兼容回退。

## HMAC v1

使用小写十六进制 HMAC-SHA256。每个部署必须有独立的、至少 32 字节的 `HMAC_SECRET`，只存于 Worker Secret 与对应后端 Secret，不写入代码或配置文件。

Accounts 头像使用单独的 `ACCOUNTS_AVATAR_HMAC_SECRET`，不得与 Wiki 的 `HMAC_SECRET` 共用。

内部请求头：

```text
X-Media-Timestamp: 10 位 Unix 秒
X-Media-Content-SHA256: 请求体 SHA-256（无请求体时为 e3b0...b855）
X-Media-Signature: HMAC-SHA256 十六进制
```

内部签名原文（末尾不加换行）：

```text
v1
{UPPERCASE_METHOD}
{canonical_path[?sorted_canonical_query]}
{timestamp}
{body_sha256}
```

查询参数按参数名、参数值排序后，以严格 RFC 3986 编码。对象路径使用规范化后的键。例如：

```text
v1\nPUT\n/internal/object/Photos/%E6%B5%8B%E8%AF%95/a.jpg\n1720000000\n{sha256}
```

下载签名原文：

```text
v1
{GET_OR_HEAD}
/download/{canonical_key}
{expires}
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

`GET` 与 `HEAD` 签名不可互换。`expires` 必须不晚于当前时间 120 秒。内部时间戳默认允许正负 300 秒时钟偏差。

带请求体的内部调用必须发送正确的 `Content-Length`。Worker 先验签，再以有界缓冲（默认最多 25 MiB）校验实际请求体 SHA-256；大文件必须分片。直接上传使用 R2 条件写且预先检查对象，multipart 在创建和完成前均检查冲突；完成失败会尝试 `abort`。R2 multipart complete 本身没有跨 Worker 的原子 `If-None-Match`，因此同一 key 不应并发启动多个上传，调用方仍须把 `409` 当作不可覆盖冲突。

所有声明的时间窗和上传上限都会进行范围校验；配置缺失时使用安全默认值，配置为非数字或超出安全范围时以 `503 worker_not_configured` 失败关闭。无请求体的内部接口会拒绝夹带的请求体。

## 本地验证

不启动服务器、不占用项目默认端口：

```powershell
cd cloudflare/nethub-wiki-media-gateway
npm test
wrangler deploy --dry-run --outdir .worker-build
```

`.worker-build/` 只用于本地 dry-run，已由本目录 `.gitignore` 排除。部署前执行 `wrangler secret put HMAC_SECRET`，不要建立 `.dev.vars` 并提交。
