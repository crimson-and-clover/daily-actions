# Daily Actions

自动化日常脚本与个人特工系统集合：涵盖 **AI 学术特工 (Resident Paper Agent)**、**金融与旅游外汇看板**、**全球科技要闻**、**Glados 自动签到** 与 **FFmpeg 镜像同步**。

全项目统一由现代 Python 包管理工具 **[uv](https://docs.astral.sh/uv/)** 管理，并在 GitHub Actions 中通过 `astral-sh/setup-uv` 实现秒级高速执行。

[![Paper Agent](https://github.com/crimson-and-clover/daily-actions/actions/workflows/paper-agent.yml/badge.svg)](https://github.com/crimson-and-clover/daily-actions/actions/workflows/paper-agent.yml)
[![Market & FX](https://github.com/crimson-and-clover/daily-actions/actions/workflows/market-fx.yml/badge.svg)](https://github.com/crimson-and-clover/daily-actions/actions/workflows/market-fx.yml)
[![World News](https://github.com/crimson-and-clover/daily-actions/actions/workflows/world-news.yml/badge.svg)](https://github.com/crimson-and-clover/daily-actions/actions/workflows/world-news.yml)
[![Glados Checkin](https://github.com/crimson-and-clover/daily-actions/actions/workflows/glados-checkin.yml/badge.svg)](https://github.com/crimson-and-clover/daily-actions/actions/workflows/glados-checkin.yml)

---

## 📋 功能模块与时间表 (北京时间 UTC+8)

| 模块名称 | 执行时间 | 核心功能与亮点 | 推送形式 |
| :--- | :--- | :--- | :--- |
| **🤖 Resident Paper Agent**<br>`paper-agent/` | 工作日 **08:30**<br>(UTC 00:30) | **存活于 Actions 的科研特工**：持续跟踪 **自动驾驶、世界模型 (World Models)、WAM、VLA、具身机器人** 最新论文。<br>• **长期记忆**：记忆库记录已读 ID，永不重复推荐；<br>• **DeepSeek 思考中枢**：输出核心创新破局点 + **秋招面试与工程落地切入点** + 星级评级；<br>• **记忆自进化**：跑完后自动 `git commit` 保存记忆回仓库。 | Gmail HTML 邮件 |
| **📊 金融行情与旅行汇率**<br>`market-fx/` | 周二至周六 **06:00**<br>(美股收盘后) | • **美股指数 & 科技核心**：标普500、纳指、道指、NVDA、TSLA、GOOGL 等；<br>• **黄金与避险**：COMEX黄金、美元指数、美债10年收益率；<br>• **年底旅行外汇**：**澳元 (AUD/CNY)** 近30天走势与低位换汇建议、**越南盾 (CNY/VND)** 快速换算参考。 | Gmail HTML 邮件 |
| **🌐 全球宏观、市场与计算开源内参**<br>`world-news/` | 每天 **07:35**<br>(晨间错峰速递) | • **多源一手聚合**：CNBC Markets、WSJ World、BBC World、Hacker News、GitHub Trending；<br>• **客观量化打分与过滤**：大模型执行 Impact Score (>= 7.0/10) 严格评级，彻底淘汰八卦与琐事噪音；<br>• **资本市场与资产定价传导**：深度推演重大事件对美股、大宗原油、美债收益率、汇率及科技巨头护城河的传导逻辑。 | Gmail HTML 邮件 |
| **Glados 自动签到** | 每天 **08:00** | 账号自动签到并保持会员状态。 | Actions 日志 |
| **FFmpeg 镜像同步** | 每周日 **10:00** | 监控上游 gyan.dev，新版本发布时自动打包为 GitHub Release。 | GitHub Release |

---

## ⚙️ 新工作流配置指南（3 步极速搞定）

系统支持将所有分析报告以富文本 HTML 形式**直接投递到您的个人 Gmail**。

### 第一步：获取 Gmail 应用专用密码 (App Password)
Google 账号出于安全机制，不允许脚本直接使用账号登录密码，需生成 16 位专属密码：
1. 浏览器打开 [Google 账号安全性页面](https://myaccount.google.com/security)。
2. 确保已开启 **“两步验证 (2-Step Verification)”**。
3. 在页面顶部搜索栏输入 **“应用专用密码”**（或进入 `安全性` → `两步验证` 最底部的 `应用专用密码`）。
4. 应用名称随意填写（如 `GitHub Actions`），点击生成，复制系统给出的 **16 位字母密码**（例如：`abcd efgh ijkl mnop`）。

### 第二步：获取 DeepSeek API Key（用于 Paper Agent 深度研判）
1. 登录 [DeepSeek 开放平台](https://platform.deepseek.com/)。
2. 进入 `API keys` 页面，点击创建新的 API Key，并复制密钥（以 `sk-` 开头）。

### 第三步：在 GitHub 仓库添加 Secrets
进入您的 GitHub 仓库页面：
1. 点击 **Settings** → 展开左侧 **Secrets and variables** → 点击 **Actions**。
2. 点击绿色的 **New repository secret**，依次添加以下变量：

| Secret 名称 | 必须性 | 填入内容 | 说明 |
| :--- | :--- | :--- | :--- |
| `GMAIL_USER` | **必填** | 您的 Gmail 地址（如 `youremail@gmail.com`） | 发信人邮箱 |
| `GMAIL_APP_PASS` | **必填** | 第一步生成的 16 位应用密码（去掉空格） | 发信用凭据 |
| `DEEPSEEK_API_KEY` | **建议配置** | 第二步获取的 DeepSeek 密钥 | 激活学术特工的深度研判与面试分析能力 |
| `NOTIFICATION_EMAIL` | 可选 | 接收邮件的地址（不填默认发给 `GMAIL_USER` 自己） | 收件人邮箱 |
| `COOKIES_GLADOS` | 现有任务 | Glados 站点的 Base64 编码 Cookie | 用于原有的自动签到 |

> [!TIP]
> **配置 Workflow 权限**（让 Paper Agent 能够自动持久化记忆）：  
> 在仓库页面进入 **Settings** → **Actions** → **General** → 滑动到最下方 **Workflow permissions** → 勾选 **Read and write permissions** → 点击 **Save**。

---

## 🧪 手动触发与本地测试

### 1. GitHub 网页上一键手动测试
所有新工作流均配置了 `workflow_dispatch`，无需等待定时触发：
1. 打开 GitHub 仓库的 **Actions** 标签页。
2. 在左侧列表中选择任意工作流（例如 `Resident Paper Agent` 或 `Market & Travel FX Daily Brief`）。
3. 点击右侧的 **Run workflow** 绿色按钮即可立即触发，测试邮件发送效果！

### 2. 本地使用 uv 运行与调试
无需繁琐创建虚拟环境，安装好 `uv` 后直接在仓库根目录一行命令运行：

```bash
# 1. 运行学术论文特工 (若配置了 DEEPSEEK_API_KEY 会调用大模型，未配置则优雅降级)
uv run python paper-agent/agent.py

# 2. 运行金融与旅游外汇看板 (本地未填 Gmail 会生成 preview_report.html 预览)
uv run python market-fx/report.py

# 3. 运行全球要闻与科技热点
uv run python world-news/report.py
```

*若本地未传入 `GMAIL_USER` 与 `GMAIL_APP_PASS`，脚本会自动将漂亮的 HTML 排版保存为各个目录下的 `preview_report.html`，双击即可在浏览器中查看效果。*

---

## 🛡️ 项目架构

```text
daily-actions/
├── .github/workflows/
│   ├── paper-agent.yml         # 🤖 学术特工定时与记忆回写工作流
│   ├── market-fx.yml           # 📊 金融与旅游汇率早报工作流
│   ├── world-news.yml          # 🌍 全球要闻与科技热榜工作流
│   ├── glados-checkin.yml      # 原有 Glados 签到
│   └── ffmpeg-mirror.yml       # 原有 FFmpeg 构建镜像
├── paper-agent/
│   ├── agent.py                # 特工感知-记忆-推理-行动主程序
│   └── memory/history.json     # 长期记忆库（记录已读论文与研读统计）
├── market-fx/
│   └── report.py               # 市场指标、澳元/越南盾汇率分析
├── world-news/
│   └── report.py               # BBC 国际要闻与 Hacker News 热榜
├── utils/
│   └── mailer.py               # 通用 Gmail 富文本发信与降级预览模块
├── pyproject.toml              # uv 现代项目依赖规范
└── uv.lock                     # 依赖确定性锁定清单
```
