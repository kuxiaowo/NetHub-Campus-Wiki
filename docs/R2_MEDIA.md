# Campus Wiki R2 媒体存储

生产环境的业务媒体通过私有 bucket 前的 `nethub-wiki-media-gateway` 访问。Worker
协议以 `cloudflare/nethub-wiki-media-gateway/README.md` 为准；后端实现 HMAC v1，浏览器
不会获得内部签名密钥，也不能直接调用 `/internal/*`。

## 配置

生产环境必须设置：

```dotenv
APP_ENV=production
MEDIA_STORAGE_BACKEND=r2
R2_MEDIA_GATEWAY_URL=https://wiki-media.nethub.wiki
R2_MEDIA_HMAC_SECRET=<与 Worker Secret 相同、至少 32 字节的随机值>
PUBLIC_MEDIA_BASE_URL=https://<API 域名>/media
```

`R2_DOWNLOAD_URL_SECONDS` 默认 90，不能超过 Worker 的 120 秒上限。直接上传默认最多
20 MiB，更大文件自动使用 R2 multipart；同一对象键由进程内锁串行，Worker 返回 409
时永不覆盖。

`MEDIA_STORAGE_BACKEND=local` 只允许在 `APP_ENV=development` 或 `test` 使用。生产启动
校验会拒绝本地存储。视频本体无论何种生产配置都保留在 `public/`，由后端
`/media/...` 流式响应；视频缩略图进入 R2。

反向代理必须把 `/media/*` 转发到 Wiki API 服务，保持路径不变。例如 Caddy：

```caddyfile
handle /media/* {
    reverse_proxy 127.0.0.1:3100
}
```

若误转发给静态前端，页面生成的 `/media/<视频路径>` 会返回 404。上线时用
`Range: bytes=0-1023` 请求真实视频，确认返回 `206` 和 `Content-Range`。

## 对象布局

- `Photos/`：活动图片。
- `CAS/`：CAS 项目图片。
- `avatars/`：旧 Wiki 头像（当前头像入口已迁至 Accounts）。
- `project-media/`：管理员上传的其他业务图片和文件。
- `yearbook-pages/`：Yearbook 页面原图，可通过 Worker `/media/...` 匿名读取。
- `yearbook-pdfs/`：Yearbook PDF，只能通过短时签名 `/download/...` 下载。
- `thumbnails/yearbook/`：Yearbook 的标准 WebP 缩略图；命名仍为
  `<逻辑页面路径>.image.webp`，可匿名读取。
- `documents/`：其他受保护文件。
- `thumbnails/`、`video-thumbnails/`：其他图片和视频缩略图。

Logo、CSS、JS、favicon 与 `public/assets/` 不迁移。数据库仍保存稳定的逻辑路径，
例如 `/CAS/NetHub/icon.png`，运行时才映射为 R2 对象键。

Yearbook 在数据库和 API 中仍使用 `/yearbook/<目录>/...` 逻辑路径，不保存 R2 键。
迁移和运行时会把图片、PDF、缩略图分别映射到上述三个固定前缀。旧 R2 前缀
`yearbook/` 与 `yearbook-thumbnails/` 不在 Worker 白名单中，也没有运行时兼容回退；
切换前应按新布局重新迁移，并在人工核对后单独清理旧对象。

## 迁移

脚本默认只 dry-run，默认样本是 `public/CAS`：

```powershell
python scripts/migrate_media_to_r2.py --manifest D:\temp\campus-r2-sample.json
```

确认清单后才显式执行：

```powershell
python scripts/migrate_media_to_r2.py public/CAS --execute --manifest D:\temp\campus-r2-sample.json
```

脚本逐对象写断点清单；上传前 HEAD，已有对象会比对大小及 Worker 验证上传内容后保存的
SHA-256 元数据，缺少该元数据时回读并计算 SHA-256，不同对象拒绝冲突。新上传对象始终
通过短时签名下载回读验证，大文件使用 multipart。默认不覆盖、不删除任何本地或云端对象。
恢复断点时仍会实时 HEAD 并校验哈希；云端对象缺失时重新上传，内容变化时明确失败。
源目录中的文件符号链接、目录链接、junction 或其他 reparse
point 会使迁移停止，解析后的所有源文件也必须位于 `public/` 内。不要并行运行两个包含
相同对象键的迁移进程。

完成全部非视频媒体迁移与回读校验前，不应切换生产 `MEDIA_STORAGE_BACKEND`；关闭
bucket 的公开 `r2.dev` 也必须在 Worker 自定义域名验证后进行。
