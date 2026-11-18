# VPS 调度器

VPS 常驻进程按项目内的 TOML 计划向 GitHub 发送 HTTPS POST；报告继续在 GitHub Runner 上执行，继续使用仓库 Secrets、状态分支和 Pages。VPS 不需要开放端口，也不需要 Gmail 或模型密钥。

所有定时任务统一由 `schedules.toml` 管理，GitHub 工作流不再保留 schedule。Inbox History 使用 `enabled=false` 保持暂停，工作流原有的 `if: false` 也保留；恢复时两处均需调整。审查 CI 等事件驱动任务保持原触发方式。GitHub 排队和报告执行仍会耗时，不能保证指定时间收到邮件。

默认时区明确为 `Asia/Shanghai`，APScheduler 和每个 CronTrigger 都显式使用配置时区，容器与 VPS 的系统时区不会改变触发时间。日志统一显示北京时间及 `+08:00` 偏移；数据库中的计划时间使用 UTC 保存，避免时间标识歧义。

## 部署

需要安装 Docker Engine 和 Compose 插件，并确保 Docker 开机启动。

创建 Fine-grained PAT，仅授权此仓库，Repository permissions 中设置 **Actions: Read and write**。Token 只用于触发工作流；留意有效期，到期后更新配置并重建容器。

在仓库根目录执行：

```bash
cp deploy/scheduler/.env.example deploy/scheduler/.env
chmod 600 deploy/scheduler/.env
# 编辑 .env，填入 GITHUB_TOKEN，不要提交该文件
docker compose -f deploy/scheduler/compose.yml build
docker compose -f deploy/scheduler/compose.yml run --rm scheduler \
  /app/.venv/bin/python -m ci_scheduler --config /app/schedules.toml --check
```

`--check` 仅校验并显示下一次执行时间，不请求 GitHub、不写触发记录。

**切换顺序：先准备并校验 VPS，再将移除全部 GitHub schedule 的修改合入 master，随后启动容器。不要在 GitHub schedule 仍启用时启动调度进程，否则会重复发信。也不要在 VPS 尚未准备时合并移除计划的修改，以免漏执行。**

```bash
docker compose -f deploy/scheduler/compose.yml up -d
docker compose -f deploy/scheduler/compose.yml logs --tail=100 -f
```

不需要逐个修改系统 timer。`restart: unless-stopped` 使容器在进程异常退出或 Docker 重启后恢复；主动停止的容器需再次启动。

## 修改时间与任务

编辑 `schedules.toml`，然后重启：

```bash
docker compose -f deploy/scheduler/compose.yml restart scheduler
```

`cron` 为 APScheduler 的五段表达式，建议用 `mon` 至 `sun` 表示星期（数字星期一为 0，星期日为 6），例如 `15 6 * * tue-sat`；时区由 `timezone` 指定。月日与星期同时受限时使用 AND 语义，与传统 cron 的 OR 语义不同。每个 workflow 只能出现一次；设置 `enabled=false` 可暂停其定时派发（默认启用），修改后重启生效。被触发的工作流必须已支持 `workflow_dispatch`；新增任务时也要在工作流配置运行互斥，不再添加 GitHub schedule。

配置中的 `ref` 默认是 master；测试分支时可显式修改它。调度由 APScheduler 3.x 管理，使用 `coalesce=True` 合并积压、`misfire_grace_time=grace_seconds` 限制补执行窗口、`max_instances=1` 防止同一个派发函数重叠执行。不同任务可并行发请求；远端工作流运行互斥仍由 GitHub concurrency 管理。修改配置后不会追赶五分钟之前的任务。

更新代码：拉取新代码后执行 `docker compose -f deploy/scheduler/compose.yml up -d --build`。修改 Token 后执行同一命令以重新创建容器；仅 `restart` 不会加载新的环境变量。

## 重启与失败处理

- APScheduler 使用内存任务存储，启动时从 TOML 重建计划，Token 不序列化到数据库；重建时从补执行窗口开始，由 APScheduler 合并最近的积压。
- `scheduler-state` Docker volume 保存 SQLite 记录，以仓库、工作流、ref 和计划时间为唯一键。保留该卷，重启不会重新派发同一次计划。不要用 `down -v` 或多个独立部署来管理同一组计划。
- 发请求前先写入 `dispatching`。正常返回后为 `submitted`，包含 GitHub 运行链接（旧版 204 响应仅有工作流页链接）。它只表示请求成功，不表示任务或邮件投递完成。
- 超时、断线或 HTTP 5xx 标记为 `unknown`，其他 API 错误标记为 `failed`；进程在请求中途退出会保留 `dispatching`。所有这些状态均**不自动重试**，避免请求实际上已成功时重复发信。启动时会提示遗留的未知请求。
- `grace_seconds=300`：重启时只允许派发最近五分钟内的计划。停机超过此窗口就跳过，避免把几天的邮件集中补发。
- API 请求日志不打印 Token。日志使用 Docker 轮转；SQLite 历史记录保留在 volume 中。

查看派发历史：

```bash
docker compose -f deploy/scheduler/compose.yml exec scheduler \
  /app/.venv/bin/python -c "import sqlite3; c=sqlite3.connect('/data/dispatches.sqlite3'); print(*c.execute('SELECT workflow, scheduled_at, status, detail FROM dispatches ORDER BY scheduled_at DESC LIMIT 20'), sep='\n')"
```

遇到 `unknown` / `dispatching`，先在 GitHub Actions 核对该时间是否已有运行，再决定是否手动触发。`failed` 应先修复权限、Token 或工作流配置，再手动补触发；不要清空数据库来重试。当前没有失败通知服务，需查看容器日志和 GitHub 运行结果。

## 本地检查

```bash
uv sync --group scheduler --frozen
uv run --group scheduler python -m ci_scheduler --check
```

本地运行调度进程需要显式设置 `GITHUB_TOKEN`，不会加载项目根目录的 `.env`。实际运行会派发任务并可能发送邮件。状态默认写入已忽略的 `state/ci-scheduler/`。

参考：[GitHub dispatch API](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)、[Compose restart 策略](https://docs.docker.com/reference/compose-file/services/#restart)。

## 默认计划（北京时间）

| 任务 | 计划 |
| --- | --- |
| Market FX | 周二至周六 06:15 |
| World News | 每天 07:35 |
| Inbox Agent | 每天 08:10、13:10、20:10 |
| Paper Agent | 周一至周五 08:35 |
| GLaDOS | 每天 08:20 |
| FFmpeg | 每周日 10:15 |
| Reviewer Radar | 每月 1、6、11、16、21、26、31 日（如存在）08:30 |
| Inbox History | 暂停；预留每天 03:25 |

Reviewer Radar 保留旧 `*/5` 的月日步进语义，不是连续每隔 120 小时。
