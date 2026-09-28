# 评论审核

Wiki 与 CAS 继续由 SQLite 提供在线读写。新评论与 `_moderation_jobs` 在同一事务保存，响应后的 BackgroundTasks 回调使任务可领取。中断的派发回调在 30 秒后恢复；运行中的任务使用超时加 60 秒的租约。AI 只隐藏，不自动删除或处罚账号。

独立的 `nethub_moderation.service` 在 `127.0.0.1:3500` 运行。两站通过各自管理员权限代理共享配置，审核服务公平领取两站内部任务，总并发默认 2。内部接口同时要求 loopback 客户端与至少 32 字符的 `MODERATION_TOKEN`。Caddy 必须拒绝 `/internal/moderation/*`，该端口不得对外开放。

两站环境增加 `MODERATION_TOKEN` 和 `MODERATION_SERVICE_URL=http://127.0.0.1:3500`。审核服务环境含同一令牌，以及 `MODERATION_DATA_DIR=/srv/nethub/data/moderation`、`MODERATION_SITES=http://127.0.0.1:3100,http://127.0.0.1:3300`。配置库和 Fernet 加密密钥位于这个独立目录，权限分别为 0600；目录 0700。备份时同时保存数据库和密钥，禁止提交到仓库或 D1。

Codex 使用专用 `CODEX_HOME`，不共享其他服务配置。管理员后台通过设备验证码完成官方 ChatGPT 登录，再自动读取全部模型及推理强度。只有 `thread/start` 使用全局锁，`turn/start` 和生成并行。创建超时禁止在原连接重发，待当前已知任务结束后重建专用连接。模型返回需同时满足最终 agentMessage、成功 turn/completed 和严格结果校验。工具禁用，无法执行评论中的指令。

OpenAI 兼容服务的 Base URL 应包含接口版本路径（如 `/v1`）。自动发现使用 `/models`，审核使用 `/chat/completions`。仅当服务明确拒绝 response_format 时逐级降级 json_schema → json_object → 文本，所有结果均校验同一约束。密钥保存后不会返回浏览器；空密钥输入保留已有值。

管理员删除必须选择最终原因；通知不包含原文、摘要或 AI 原文证据。清空正文并保留回复关系，通知、审核结案和评论变化原子提交。重复删除不重复通知。忽略只能恢复 AI 暂时隐藏的内容，迟到的结果不能覆盖人工决定。审核失败最多三次后公开转人工；额度耗尽暂停领取等待恢复，不耗尽重试次数。

## 数据迁移及镜像

Wiki 迁移 017 增加本地审核任务与系统通知。CAS v4 → v5 安全重建 comments 的状态约束，保留全部 ID、回复关系、索引，并恢复与验证外键。迁移应先在完整生产副本演练。

`_moderation_*` 表被镜像工具明确排除。system_notifications 与 comments 是业务数据，需更新 D1 schema、捕获触发器及镜像基线。停止镜像交付进程，保留 outbox，做 SQLite 在线备份；应用迁移后重新安装捕获触发器、生成新快照、核验并重建 D1 基线，再 arm 恢复交付。禁止直接删 outbox 或将 D1 切为在线库。

离线迁移命令：`python -m scripts.migrate_moderation --site wiki --db <sqlite> --backup <new-backup>`（CAS 使用 `--site cas`）。先停止对应 API、镜像 worker 与健康检查定时器。该命令把 schema 与捕获触发器更新放在同一事务，保留所有 outbox，并将交付置为未启用。Wiki 兼容当前 v15/v16，最终 v17；CAS 从 v4 到 v5。

D1 DDL 位于 Wiki 的 `sql/d1/017_comment_moderation.sql` 与 CAS 的 `sql/d1/005_comment_moderation.sql`，不含本地审核任务。执行前检查远端实际结构并导出备份。Wiki DDL 包含 v16 的 `turnstile_verified_at`，若该字段已经存在，跳过这条 ALTER。用 Wrangler 的 D1 官方接口执行，不使用运行时 DML 网关。

停止交付后记录远端水位 N。迁移后生成 snapshot，并用 `d1_reconcile.py --migration-watermark N --apply` 重建基线；此参数严格核对原水位并保留 `_sync_events` 历史。执行 `--verify-only` 后用 `d1_mirror.py arm` 确认新水位与快照一致，再恢复 worker 和健康检查。快照之后的在线写入仍通过捕获触发器保存，后续按序重放。

回退保留原发布目录、迁移前 SQLite 完整备份与 D1 水位快照；出现错误时先保留迁移后的数据库及新写入，避免回退时覆盖新评论。未完成镜像基线的服务不得宣称镜像健康。

## 验证

运行两站现有测试以及 test_comment_moderation；Wiki 另运行 test_moderation_service。检查匿名及普通用户无法进入后台、外部客户端无法调用内部接口、通知按收件人隔离、隐藏正文不出现在列表／上下文／互动通知。

配置未就绪时评论保持公开、任务保留，后台明确显示待配置。生产真实 AI 验证需要管理员完成服务器 Codex 登录或配置兼容接口凭据；模拟测试不能替代真实云端调用验收。
