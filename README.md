<div align="center">

# ⚡ Daily Actions

**自动化日常作业系统与个人智能特工集群**

面向个人生产力构建的无服务器（Serverless）日常自动化任务调度平台，涵盖 **AI 学术特工 (Resident Paper Agent)**、**全球宏观与金融简报**、**全球资讯内参**、**云服务状态维护** 与 **构建镜像同步**。

[![CI Architecture](https://img.shields.io/badge/CI%2FCD-GitHub%20Actions-2088FF?logo=github-actions&logoColor=white)](https://github.com/crimson-and-clover/daily-actions/actions)
[![Environment](https://img.shields.io/badge/Runtime-Python%203.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Package Manager](https://img.shields.io/badge/Manager-uv%20(Astral)-DE5FE9?logo=astral&logoColor=white)](https://docs.astral.sh/uv/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](#)

[![Paper Agent](https://github.com/crimson-and-clover/daily-actions/actions/workflows/paper-agent.yml/badge.svg)](https://github.com/crimson-and-clover/daily-actions/actions/workflows/paper-agent.yml)
[![Market & FX](https://github.com/crimson-and-clover/daily-actions/actions/workflows/market-fx.yml/badge.svg)](https://github.com/crimson-and-clover/daily-actions/actions/workflows/market-fx.yml)
[![World News](https://github.com/crimson-and-clover/daily-actions/actions/workflows/world-news.yml/badge.svg)](https://github.com/crimson-and-clover/daily-actions/actions/workflows/world-news.yml)
[![Glados Checkin](https://github.com/crimson-and-clover/daily-actions/actions/workflows/glados-checkin.yml/badge.svg)](https://github.com/crimson-and-clover/daily-actions/actions/workflows/glados-checkin.yml)
[![FFmpeg Mirror](https://github.com/crimson-and-clover/daily-actions/actions/workflows/ffmpeg-mirror.yml/badge.svg)](https://github.com/crimson-and-clover/daily-actions/actions/workflows/ffmpeg-mirror.yml)

</div>

---

## 📖 项目愿景与架构特性

本项目旨在构建一个高稳定性、免维护、低延迟的云端自动化中枢：

- **统一单 Python 运行时**：全仓依托现代包管理器 **[uv](https://docs.astral.sh/uv/)** 与 `pyproject.toml`，以 `uv.lock` 确定性锁定依赖，实现 0.5s 级依赖极速安装与缓存复用。
- **结构化工程规范**：严格遵循 `src/` 源码分层规范，模块职能边界清晰，解耦公共通信组件与专用任务逻辑。
- **现代化 CI/CD 编排**：采用官方最新 `astral-sh/setup-uv@v5` + `actions/checkout@v7`，保障最小安全攻击面与长期兼容性。
- **状态持久化与内容分发**：
  - **Memory Persistence**：通过独立的 `agent-state` 孤儿分支持久化存储 Agent 演进记忆与学术去重状态。
  - **Static Site Delivery**：自动生成静态化报告归档，通过 `gh-pages` 部署至 GitHub Pages 门户。

---

## 📋 任务调度与功能矩阵

> 调度基准时区：**北京时间 (CST / UTC+8)**

| 模块组件 | 调度周期 | 核心机制与业务价值 | 交付通道 |
| :--- | :--- | :--- | :--- |
| **🤖 Resident Paper Agent**<br>`src/paper-agent/` | 工作日 **08:30**<br>`30 0 * * 1-5 (UTC)` | **前沿 AI 学术研究 Agent**：<br>• **领域聚焦**：自动驾驶 (AD)、世界模型 (World Models)、具身感知 (VLA)、广义动作模型 (WAM) 等前沿方向；<br>• **感知与全篇研读**：自动化获取 arXiv 原生 HTML 源码，深度拆解核心机制与公式；<br>• **DeepSeek 双轮研判**：提炼白话 TL;DR、落地价值与面试切入点；<br>• **持久记忆库**：双向同步 `agent-state` 分支，彻底避免重复推演。 | • Gmail 邮件<br>• Pages 网页端 |
| **📊 Market & FX Brief**<br>`src/market-fx/` | 周二至周六 **06:00**<br>`0 22 * * 1-5 (UTC)` | **全球资产定价与旅行外汇风向标**：<br>• 追踪美股核心大盘 (S&P 500, Nasdaq, Dow Jones) 与科技巨头 (NVDA, TSLA, MSFT 等) 收盘表现；<br>• 宏观定锚：黄金价格、美元指数 (DXY)、美国 10 年期国债收益率；<br>• 智能外汇策略：澳元 (AUD/CNY)、越南盾 (CNY/VND) 走势追踪与换汇区间建议。 | • Gmail 邮件 |
| **🌐 World News & Intelligence**<br>`src/world-news/` | 每日 **07:35**<br>`35 23 * * * (UTC)` | **宏观、资本市场与开源生态综合情报内参**：<br>• 多通道聚合：CNBC Markets、WSJ World、BBC World、Hacker News、GitHub Trending；<br>• 量化冲击评级：基于 LLM 对信息施行 Impact Score (>= 7.0/10) 严格降噪过滤；<br>• 跨市场逻辑传导：研判大宗商品、汇率与技术突破背后的产业纵深影响。 | • Gmail 邮件<br>• Pages 网页端 |
| **🛡️ GLaDOS Checkin**<br>`src/glados-checkin/` | 每日 **08:00**<br>`0 0 * * * (UTC)` | **服务状态自动化维护**：<br>• 自动化执行 API 签到并兑换权益，保障开发节点与代理账号续期活跃。 | • Actions 日志 |
| **🚀 FFmpeg Auto Sync**<br>`src/ffmpeg-mirror/` | 每周日 **10:00**<br>`0 2 * * 0 (UTC)` | **上游构建自动镜像与分发**：<br>• 轮询 gyan.dev 最新二进制版本；<br>• 自动比对差异，触发 Release 打包并上传 GitHub Release 资产。 | • GitHub Release |

---

## 🏗️ 目录工程结构

```text
daily-actions/
├── .github/
│   └── workflows/                # 声明式 GitHub Actions 编排配置
│       ├── ffmpeg-mirror.yml     # FFmpeg 自动化构建发布工作流
│       ├── glados-checkin.yml    # GLaDOS 状态续订工作流
│       ├── market-fx.yml         # 宏观金融与汇率早报工作流
│       ├── paper-agent.yml       # 学术研究特工工作流 (含记忆分支回写)
│       └── world-news.yml        # 全球资讯与 Pages 静态站点部署工作流
├── docs/                         # GitHub Pages 静态文档归档产物
│   ├── index.html                # 门户主页导航
│   ├── paper-agent/              # 论文报告站点目录
│   └── world-news/               # 资讯报告站点目录
├── src/                          # 任务源码根目录
│   ├── ffmpeg-mirror/            # 镜像同步脚本集
│   ├── glados-checkin/           # 自动签到核心实现
│   ├── market-fx/                # 金融汇率指标抓取与模板渲染
│   ├── paper-agent/              # 论文抓取、HTML 解析与 LLM 多轮推理
│   ├── utils/                    # 跨任务公共基础设施 (SMTP 邮件传输引擎)
│   └── world-news/               # 多源资讯聚合器与报告生成器
├── .env                          # 本地环境变量配置（本地开发，已被 Git 忽略）
├── .gitignore                    # 忽略规则清单
├── .python-version               # 运行环境 Python 3.12 基准版本
├── pyproject.toml                # 项目元数据与全局统一依赖规范
├── uv.lock                       # 依赖确定性锁文件
├── template_portal.html          # Pages 门户主页渲染模板
└── README.md                     # 项目主文档
```

---

## 🚀 快速上手与配置指引

### 1. 仓库凭据配置 (GitHub Secrets)

进入 GitHub 仓库页面：`Settings` → `Secrets and variables` → `Actions` → `New repository secret`，按需添加以下环境变量：

| 变量名称 | 必需性 | 作用描述 | 示例 / 说明 |
| :--- | :---: | :--- | :--- |
| `GMAIL_USER` | **必需** | Gmail 发信主账号 | `example@gmail.com` |
| `GMAIL_APP_PASS` | **必需** | Google 账号专用应用密码 | 16 位安全应用密码 (非登录密码) |
| `NOTIFICATION_EMAIL` | 可选 | 接收通知的目标邮箱 | 留空时默认发送至 `GMAIL_USER` |
| `DEEPSEEK_API_KEY` | **必需*** | 用于论文深度精读与要闻研判的大模型密钥 | `sk-xxxxxxxxxxxxxxxxxxxxxxxx` |
| `COOKIES_GLADOS` | 可选 | GLaDOS 鉴权 Cookie (Base64) | 仅 GLaDOS 签到任务需要 |

> [!IMPORTANT]
> **开启 Workflow 读写权限 (必要)**：  
> `paper-agent` 需要自动更新状态至 `agent-state` 分支，`world-news` 需要发布至 `gh-pages` 分支。  
> 请务必在仓库进入：**Settings** → **Actions** → **General** → 找到 **Workflow permissions**，勾选 **Read and write permissions** 并保存。

### 2. 本地开发与调试环境搭建

项目采用现代 Python 包管理工具 `uv`，无需繁琐的虚拟环境配置。

#### 安装 uv
```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Linux / macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### 本地同步与运行
```bash
# 1. 克隆代码仓库
git clone git@github.com:crimson-and-clover/daily-actions.git
cd daily-actions

# 2. 一键同步并安装全部依赖
uv sync

# 3. 配置本地环境变量 (项目已提供 .env 模板)
# 编辑根目录 .env 文件，填入对应的凭据

# 4. 执行任意任务 (本地无邮件凭据时会自动降级保存为 preview_report.html)
uv run python src/market-fx/report.py
uv run python src/world-news/report.py
uv run python src/paper-agent/agent.py
```

---

## 🔒 分支架构策略 (Branch Architecture)

- **`master`**：主开发分支，维护所有任务源码、Workflow 定义与静态网页模板。
- **`agent-state`**：状态孤儿分支，用于解耦 `paper-agent` 的历史运行状态 (`history.json`)，避免高频日志污染主分支提交记录。
- **`gh-pages`**：文档托管分支，由 `actions-gh-pages` 自动生成，专供 GitHub Pages 静态站点部署与访问。

---

## 📄 开源许可证

本项目基于 [MIT License](LICENSE) 许可证发布。
