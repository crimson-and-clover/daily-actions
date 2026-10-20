<div align="center">

# ⚡ Daily Actions

**个人日常自动化作业系统 (Serverless Automated Daily Tasks)**

[![CI/CD](https://img.shields.io/badge/CI%2FCD-GitHub%20Actions-2088FF?logo=github-actions&logoColor=white)](https://github.com/crimson-and-clover/daily-actions/actions)
[![Runtime](https://img.shields.io/badge/Runtime-Python%203.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Manager](https://img.shields.io/badge/Package-uv-DE5FE9?logo=astral&logoColor=white)](https://docs.astral.sh/uv/)
[![Linter & Formatter](https://img.shields.io/badge/Linter%20%26%20Formatter-Ruff-black?logo=ruff&logoColor=white)](https://docs.astral.sh/ruff/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](#)

[![Paper Agent](https://github.com/crimson-and-clover/daily-actions/actions/workflows/paper-agent.yml/badge.svg)](https://github.com/crimson-and-clover/daily-actions/actions/workflows/paper-agent.yml)
[![Inbox Agent](https://github.com/crimson-and-clover/daily-actions/actions/workflows/inbox-agent.yml/badge.svg)](https://github.com/crimson-and-clover/daily-actions/actions/workflows/inbox-agent.yml)
[![Inbox History Agent](https://github.com/crimson-and-clover/daily-actions/actions/workflows/inbox-history-agent.yml/badge.svg)](https://github.com/crimson-and-clover/daily-actions/actions/workflows/inbox-history-agent.yml)
[![Market FX](https://github.com/crimson-and-clover/daily-actions/actions/workflows/market-fx.yml/badge.svg)](https://github.com/crimson-and-clover/daily-actions/actions/workflows/market-fx.yml)
[![World News](https://github.com/crimson-and-clover/daily-actions/actions/workflows/world-news.yml/badge.svg)](https://github.com/crimson-and-clover/daily-actions/actions/workflows/world-news.yml)
[![Glados Checkin](https://github.com/crimson-and-clover/daily-actions/actions/workflows/glados-checkin.yml/badge.svg)](https://github.com/crimson-and-clover/daily-actions/actions/workflows/glados-checkin.yml)
[![FFmpeg Sync](https://github.com/crimson-and-clover/daily-actions/actions/workflows/ffmpeg-mirror.yml/badge.svg)](https://github.com/crimson-and-clover/daily-actions/actions/workflows/ffmpeg-mirror.yml)

</div>

---

## ⚡ 任务调度与功能矩阵

> 调度基准时区：**北京时间 (CST / UTC+8)**。点击对应组件名可查看该模块详细设计与配置。

| 模块组件 | 调度周期 | 核心职能与业务价值 | 交付通道 | 详细配置 |
| :--- | :--- | :--- | :--- | :---: |
| **📬 Inbox Agent** | 每日 08:10 / 13:10 / 20:10<br>`10 0,5,12 * * * UTC` | **日常收件箱智能整理**：四维分类分流，日程待办提炼，自动归档 `商业推广`/`系统通知`，绝不物理硬删 | Gmail 卡片 | [README](src/inbox_agent/README.md) |
| **📦 Inbox History** | *已暂停调度 (暂时停用)* | **90天历史积压整理**：从最旧到较新按 10 封小批次研判，过期废件移入回收站，历史凭证与推广分类归档 | Gmail 报告 | [README](src/inbox_agent/README.md) |
| **🤖 Paper Agent** | 工作日 08:35<br>`35 0 * * 1-5 UTC` | **AI 论文追踪**：追踪 8 大前沿赛道，大模型初筛与全文精读，提取方法架构图并探测官方存活开源代码 | Gmail / Pages | [README](src/paper_agent/README.md) |
| **📊 Market FX** | 周二至周六 06:15<br>`15 22 * * 1-5 UTC` | **宏观资产与外汇早报**：主流外汇追踪、澳元真分位数、越南盾三角套算、美股科技大盘与大宗指标 | Gmail / Pages | [README](src/market_fx/README.md) |
| **🌐 World News** | 每日 07:35<br>`35 23 * * * UTC` | **全球资讯与开源动态**：聚合 CNBC / WSJ / BBC / HN / GitHub，LLM Impact Score (>=7.0) 降噪过滤 | Gmail / Pages | [README](src/world_news/README.md) |
| **🛡️ Glados Checkin**| 每日 08:20<br>`20 0 * * * UTC` | **服务状态维护**：自动签到与权益兑换，维持开发节点和代理账号活跃 | CI 日志 | [README](src/glados_checkin/README.md) |
| **🚀 FFmpeg Sync** | 每周日 10:15<br>`15 2 * * 0 UTC` | **镜像自动同步**：轮询上游 gyan.dev 最新构建版本，打包发布至 GitHub Release | GitHub Release | [README](src/ffmpeg_mirror/README.md) |

---

## 🛠️ 工程化与设计哲学

- **统一面向对象路径 (`pathlib.Path`)**：全工程彻底杜绝裸 `str` 路径，保证 Windows/Linux 跨平台绝对鲁棒。
- **配置自闭环与启动预校验 (`validate_config`)**：各任务独立维护自身 `config.py`，入口统一快速失败（Fail-Fast），绝不中途静默崩溃。
- **邮件服务纯函数解耦 (`utils.mailer`)**：基于 `redmail` 现代化邮件引擎与 `tenacity` 指数退避，发送方法接受显式凭证入参。
- **极速代码质量流水线 (`Ruff`)**：基于 Ruff 统一管理 Lint 与 Format，严格保障 0 Warning / 0 Error 代码规范。

---

## 🔑 凭据配置速查 (GitHub Secrets)

仓库主页：`Settings` → `Secrets and variables` → `Actions` → `New repository secret`：

| 变量名称 | 必需性 | 作用描述 | 关联组件 |
| :--- | :---: | :--- | :--- |
| `GMAIL_USER` | **必需** | Gmail 发信账号 | `inbox-agent`, `paper-agent`, `market-fx`, `world-news` |
| `GMAIL_APP_PASS` | **必需** | Google 专用 16 位应用密码 (非登录密码) | `inbox-agent`, `paper-agent`, `market-fx`, `world-news` |
| `NOTIFICATION_EMAIL`| 可选 | 接收通知的目标邮箱 (默认同 `GMAIL_USER`) | `inbox-agent`, `paper-agent`, `market-fx`, `world-news` |
| `DEEPSEEK_API_KEY` | **必需** | 驱动学术精读、要闻降噪与收件箱分流的大模型密钥 | `inbox-agent`, `paper-agent`, `world-news` |
| `INBOX_STATE_KEY` | **必需** | 收件箱记忆库 AES 对称加密密钥 (`python scripts/generate_inbox_key.py`) | `inbox-agent`, `inbox-history-agent` |
| `COOKIES_GLADOS` | 可选 | GLaDOS 鉴权 Cookie (支持 Base64 或原始文本) | `glados-checkin` |

> [!IMPORTANT]
> **开启 Workflow 读写权限 (必需)**：  
> Agent 需要向各自 `state/{ci-name}` 分支持久化加密记忆，研报需推送到 `gh-pages` 分支。  
> 请在仓库 **Settings** → **Actions** → **General** → **Workflow permissions**，勾选 **Read and write permissions** 并保存。

---

## 🏗️ 目录工程结构

```text
daily-actions/
├── .github/workflows/       # 声明式 GitHub Actions 编排配置
├── docs/                    # GitHub Pages 静态门户与研报历史归档
├── scripts/                 # 运维工具 (如 generate_inbox_key.py)
├── src/                     # 标准 Python 模块源码根目录 (各组件均含独立 README)
│   ├── inbox_agent/         # 📬 收件箱智能分流、DDL提炼与 90 天历史沉淀归档
│   ├── paper_agent/         # 🤖 前沿 AI 学术研究追踪与两阶段研判
│   ├── market_fx/           # 📊 宏观金融、外汇矩阵与美股指标
│   ├── world_news/          # 🌐 全球多源资讯聚合与量化研判
│   ├── glados_checkin/      # 🛡️ GLaDOS 自动签到保活
│   ├── ffmpeg_mirror/       # 🚀 FFmpeg 上游构建镜像同步
│   └── utils/               # 公共组件 (邮件分发引擎、页面生成器、Prompt 渲染器与时区工具)
├── pyproject.toml           # 项目元数据与依赖定义 (基于 uv 与 hatchling)
└── uv.lock                  # 依赖确定性锁文件
```

---

## 💻 本地极速调试

项目依托现代 Python 包管理工具 **[uv](https://docs.astral.sh/uv/)** 与代码检查工具 **[Ruff](https://docs.astral.sh/ruff/)**：

```bash
# 1. 克隆代码并安装依赖
git clone git@github.com:crimson-and-clover/daily-actions.git
cd daily-actions && uv sync

# 2. 配置本地 .env (仓库提供标准模板)
cp .env.example .env  # 填入凭据，本地无凭据时自动降级为保存 preview 文件

# 3. 运行任意任务
uv run python -m inbox_agent.agent
uv run python -m inbox_agent.history_agent
uv run python -m paper_agent.agent
uv run python -m market_fx.report
uv run python -m world_news.report

# 4. 代码规范检查与格式化 (宽度 256)
uv run ruff check src/ scripts/
uv run ruff format src/ scripts/
```

---

## 🔒 分支架构策略

- **`master`**：主开发分支，维护核心源码、工作流定义与依赖锁文件。
- **`state/{ci-name}`**：各任务专属的独立持久化状态分支（如 `state/inbox-agent`, `state/paper-agent`），彻底解耦并发冲突。
- **`gh-pages`**：静态网站托管分支，由 CI 自动增量构建发布全站门户与历史研报归档。

---

## 📄 开源许可证

本项目基于 [MIT License](LICENSE) 许可证开源发布。
