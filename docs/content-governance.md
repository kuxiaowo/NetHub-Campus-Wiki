# 账号与内容治理发布说明

## 用户与管理员入口

账号中心采用邀请注册：北京时间每天生成一份单次邀请，额度不累积，撤销不退额度，凭证七天有效；邮箱验证后才能发言，首次验证满 72 小时才能邀请。验证邮件由 Resend 队列发送，确认页 GET 不消费凭证，带 CSRF 的 POST 才确认。

Wiki 个人中心显示邮箱验证、本站禁言原因与期限，以及评论、项目动态和个人简介的提交状态。普通成员的这些公开内容在 AI 通过前保持私有；图文动态的图片同时审核。审核服务异常、结果不合法、作者资格无法确认或模型发现疑点时保持隐藏，交人工复检。管理员发布免 AI，但记录实际操作者。本站禁言同时限制评论、动态、简介和私信发送。

管理后台“用户管理”提供本站禁言/解禁及原因、期限；暂停邀请和全站封禁在 Accounts 管理页处理。“内容审核”包含评论队列和动态/简介队列；人工批准、拒绝或重试需要原因，保留审计记录。已公开历史内容保持原状态，新提交遵循预审。

申诉通过管理员微信办理，不建立工单或证件上传系统。提供真实姓名、学校/班级；必要证明可遮挡无关信息，处理完成后删除。上线前必须配置 Accounts 的 `APPEAL_WECHAT_ID`，确认匿名可打开申诉制度页。

Todo、TechX、Wiki 和 CAS 每次受保护访问核验 Accounts 状态：全站封禁返回 403 并撤销本地会话；状态服务无法确认时返回 503，不继续授权。退出入口仍可使用。客户端状态请求禁止重定向，避免客户端凭证被带到其他地址。

CAS 图集站永久移除评论、点赞、举报、通知、消息中心与审核功能，只保留图集媒体和公告；旧数据库按该仓库的离线移除脚本升级。

## 数据库与旧接口

SQLite 是在线主库，D1 仅作公开数据镜像。Wiki v20 将项目动态从 `projects.updates` JSON 移至 `project_updates`，旧列删除，在线导入仅接受 v3。旧 v1/v2 导出须先运行 `python -m scripts.convert_transfer_v3 old.json new-v3.json`，输出文件必须尚不存在。

v3 中 `/api/content-media/<id>` 只能引用同站已公开、且当前项目动态仍使用的图片，不能引用待审图片。此类导出 JSON 不能独立迁移媒体至另一站，恢复时需要主库、私有媒体目录或 R2 对象一起备份，并核对公开引用。不要把私有媒体改放公开目录。

`_private_content_submissions`、`_private_content_media`、`_moderation_content_jobs` 和 `_moderation_jobs` 必须排除在镜像捕获和公开导出之外。普通数据库迁移不允许在已启用镜像捕获的库上直接执行此次结构调整。

## 发布顺序

1. 先发布 Wiki 媒体 Worker，开启 `PRIVATE_REVIEW_MEDIA_ENABLED="true"`。`review-media/<32位hex>.jpg` 只允许内部签名和短时签名下载；`/media/` 永远拒绝。Accounts 头像 Worker 不开启此开关，继续使用独立 bucket 和签名密钥。
2. 检查并备份 Accounts 主库、Wiki/CAS 主库和媒体，停止应用写入与镜像投递。Accounts 执行 Alembic 升级；确认 Resend 配置、发件域验证、微信申诉配置及各站客户端凭证。
3. Wiki v19 库使用 `python -m scripts.migrate_content_governance --db /absolute/wiki.db --backup /absolute/new-backup.db`。备份文件不得已存在。迁移及 JSON 转换处于同一写事务，损坏 JSON 导致回滚；历史动态 ID 保留。
4. 有 `_sync_control` 的数据库必须额外传 `--mirror-module /verified/path/d1_mirror.py`，先核验真实工具，脚本验证捕获、暂停 ready、重建触发器、确认私有表不被镜像。不得用临时 stub 代替真实工具。CAS 同样使用本仓库移除脚本及明确镜像模块。
5. D1 单独应用 `sql/d1/020_content_governance.sql`；随后按真实镜像工具的正式流程重新对齐快照、核验公开表和触发器，成功后才恢复投递。离线脚本不会自行恢复镜像 ready。不能只更新 SQLite 或只更新 D1。
6. 启动 Accounts、四个客户端和审核服务。审核服务 `MODERATION_SITES` 只指向 Wiki（通常为 `http://127.0.0.1:3100`），删除旧 CAS 站点配置。安装并启用 `config/nethub-wiki-governance-cleanup.service` 与 `.timer`，根据现场调整 Python 路径和环境文件。
7. 验证完整邀请注册、真实邮件投递、72 小时限制、文字/图片 AI 审核、人工复检、禁言/暂停邀请/全站封禁、申诉说明，以及各站会话撤销。发布需按约定先汇入 `developing` 提交，再 PR 合并 `main`。

2026-10-01 只读现场检查未找到技能快照所记载的 `d1-mirror` 目录、`d1_mirror.py` 或镜像 systemd unit。不能据此断言生产没有其他镜像机制；发布前须确认实际机制和工具位置。本地回归没有验证生产镜像迁移，也没有发送真实邮件或调用真实 AI。

## 保留期限

Accounts worker 每天清理：过期验证记录 30 天、注销后的邀请关系 180 天、账号处罚审计 365 天，也可执行 `flask --app app:create_app governance cleanup`。

Wiki `python -m scripts.cleanup_governance` 每天清理：拒绝/撤回且未被公开动态使用的私图 30 天；终态审核详情、提交副本及通知摘录 180 天；处罚审计 365 天。媒体删除失败保留数据库记录等待重试。迁移备份应在恢复窗口结束后最多保留 30 天，按服务器既有备份策略清理。

清理脚本不扫描未入库的 R2 上传孤儿。运维应定期按对象与主库核对孤儿，至少保留 30 天且确认没有公开引用后再清理，避免删除仍被使用的图片。
