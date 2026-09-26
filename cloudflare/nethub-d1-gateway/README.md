# NetHub Campus Wiki D1 gateway

独立的 Cloudflare Worker 数据网关，供站点服务端通过 `POST /internal/db` 访问各自的 D1 binding。该目录不包含任何生产 `database_id`，不会自动创建或初始化数据库。

## 请求签名

请求体是 JSON，包含与签名头一致的 `requestId`、`timestamp`、`mode`（`single` 或 `batch`）和 1–100 条 `{sql, params}`。客户端使用以下请求头：

- `X-DB-Request-ID`：每次请求唯一的随机 ID；
- `X-DB-Timestamp`：Unix 秒；
- `X-DB-Signature`：HMAC-SHA256 hex。

签名明文为 `v1\nPOST\n/internal/db\nrequestId\ntimestamp\nsha256(body)`。网关校验时间偏差、请求 ID 重放和 body 摘要。写语句使用 D1 `run()`，查询语句使用 `all()`，batch 使用 D1 `batch()`。

运行时只接受 SELECT/INSERT/UPDATE/DELETE/WITH/EXPLAIN，拒绝 DDL、事务控制和 PRAGMA。请求体中的 ID/时间戳必须与签名头一致。

生产配置默认 fail-closed，必须启用 `REPLAY_GUARD` Durable Object 才接受请求，从而在多 isolate 间原子认领 request ID。模板中的 binding/migration 保持注释状态，不会自行创建资源；部署时由后续基础设施阶段显式启用。`ALLOW_IN_MEMORY_REPLAY=true` 仅供单元测试，禁止用于生产。

部署前必须在每个站点单独绑定 `DB` 和设置 `HMAC_SECRET`；不要把 `database_id` 或 secret 写入仓库。
