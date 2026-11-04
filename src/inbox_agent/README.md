# 📬 Inbox Agent (收件箱智能整理助手)

基于 **Agentic ReAct (Reasoning + Acting) 工具调用架构** 与 **多轮决策** 的邮件智能助手。日常 Inbox Agent 禁止将邮件移入已删除邮件（Trash），过期或疑似重复的邮件仅归档，确认的垃圾邮件移入 Spam；日常工具入口拦截回收站写入。History Agent 仍可按历史清理规则将邮件移入 Trash，禁止物理删除。

---

## 🌟 核心架构

1. **自主工具调用 (Tool-Calling / Function Calling)**：
   - 告别硬编码脚本流水线，赋予 Agent 专属邮件工具箱（`route_emails`, `mark_email_flags`, `read_email_content`, `search_emails`, `create_calendar_event`, `list_calendar_events`, `remove_calendar_event`, `create_email_draft`）。
   - 细化多维度业务识别：验证码安全口令、银行证券动账账单、政务事务公函、商业推广、系统通知、日程待办与恶意垃圾。
   - 邮件分流、旗标、日程及关联草稿写操作前必须调用 `read_email_content` 完整阅读正文；工具层按来源邮件校验，引擎要求完整结果已在前一轮返回，截断或读取失败不放行。
2. **10 封独立上下文批次机制 (Fresh Context Batching)**：
   - 每次处理 10 封待办邮件（包括收件箱新信与垃圾箱复核），开启全新的对话上下文，根绝 Token 冗余膨胀与注意力衰减。
   - 每批次处理完毕即时将状态与加密记忆持久化（Fernet AES），容错率高。
3. **主动对账与防御加固 (Active Reconciliation & Guardrails)**：
   - 单一最终去向：每封邮件只选择一个 destination（包含留存 Inbox），程序执行分流，tracker 直接记录来源与最终去向；日程提取、已读和星标独立。History Agent 还可选择 Trash。
   - 日程先查后改：本批次首次创建或删除日程前必须先调用 `list_calendar_events` 并核对结果；工具层拦截本批次未成功查询的变更，同批次可结合查询与操作结果继续处理，无需每次重查。状态不确定时再查询核实。
   - 引擎仅认可上一轮已返回到上下文的日程查询结果，首次查询与创建/删除在同轮发起时拦截变更；垃圾箱复核仅记录显式成功处置的邮件，未决邮件保留重试机会。
   - 日程准入提示：仅提取本人已确认参与、明确被安排或必须办理的事项；普通学校活动邀请、讲座宣传与可选报名截止日只分类，不自动创建日程。改期先成功创建新日程，再删除已确认的旧日程。
   - 批次结束时主动对账未处置邮件并追加拦截催促，确立每封邮件去向。
   - 严格防御 Prompt 注入与参数畸形（如参数被错误解析为列表时的防御性规整）。
4. **模块化 IMAP 解耦架构**：
   - 底层 IMAP 操作解耦为 `inbox_agent.imap` 模块化子包（基于 `imapclient`，包含 `ImapConnection`, `MessageRepo`, `LabelService`, `FlagService`, `DraftService` 与纯净 `Email` 数据实体）。

---

## 🛠️ 工具集 (Tools Matrix)

| 工具名称 | 功能描述 |
| :--- | :--- |
| **`route_emails`** | 批量选择唯一 destination（留存 Inbox、归档或分类分流），由程序执行互斥标签变更并记录处置备忘 |
| **`mark_email_flags`** | 调整邮件已读/未读状态或标星置顶旗标 |
| **`read_email_content`** | 按 UID 深度抓取单封邮件完整正文与附件信息（按需调用，节省 Token） |
| **`search_emails`** | 按关键词、发件人或未读状态检索邮件元数据 |
| **`create_calendar_event`** | 提取会议、出行及到期日 (DDL)，自动沉淀到待办日历池 |
| **`list_calendar_events`** | 查看当前活跃的待办日程列表 |
| **`remove_calendar_event`** | 取消或移除失效的日程待办 |
| **`create_email_draft`** | 在 Gmail 草稿箱拟定回复或新信（遵循安全原则，绝不未经确认直发邮件） |

---

## ⚙️ 组件构成与调度

| 组件脚本 | 对应工作流 | 调度周期 (北京时间) | 职能定义 |
| :--- | :--- | :--- | :--- |
| **`agent.py`** | `.github/workflows/inbox-agent.yml` | 每日 08:10 / 13:10 / 20:10 | **日常实时分流**：10 封一组 ReAct 决策，提炼日程待办与 DDL，将推广归档至 `商业推广`，通知归档至 `系统通知`，恶意垃圾移至 `[Gmail]/Spam`，分批复核垃圾箱误杀。 |
| **`history_agent.py`** | `.github/workflows/inbox-history-agent.yml` | *已暂停调度 (暂时停用)* | **90天历史积压归档**：从最旧到较新按批次扫描超过 90 天的历史邮件，允许按历史清理规则移入 Trash，或归档、保留。 |

---

## 🔑 所需凭据 (GitHub Secrets)

| 变量名称 | 必需性 | 说明 |
| :--- | :--- :--- | :--- |
| `GMAIL_USER` | **必需** | Gmail 账号（如 `user@gmail.com`） |
| `GMAIL_APP_PASS` | **必需** | Google 专用 16 位应用密码（非登录密码） |
| `DEEPSEEK_API_KEY` | **必需** | 用于邮件多轮决策、日程提炼与工具调用的模型密钥 |
| `INBOX_STATE_KEY` | **必需** | 收件箱记忆库 Fernet AES 对称加密密钥，保护邮件隐私与状态 |
| `NOTIFICATION_EMAIL`| 可选 | 汇总邮件接收地址（默认发送至 `GMAIL_USER`） |

### 生成加密密钥
运行仓库内置脚本即可生成 `INBOX_STATE_KEY`：
```bash
uv run python scripts/generate_inbox_key.py
```

---

## 🚀 本地调试与运行

### 个人背景配置

编辑 `src/inbox_agent/user_profile.json`，分别维护 `facts`（个人事实）、`goals`（当前目标）与 `preferences`（处理偏好），三个字段均为字符串数组；暂无内容时填写空数组。日常 Agent 在连接邮箱前先校验配置，每批次构建系统提示词时继续加载最新内容，无需修改提示词模板。文件会随代码分发，请仅填写希望提供给模型的背景，不填写密码或密钥。

Profile 用于判断邮件适用性和优先级：已毕业不屏蔽具体的面试、申请进展或毕业手续；有价值的机会可以推荐，但仍须符合参与证据和先查日程等规则才创建日程。邮件内容不能自动修改 Profile；文件缺失或格式错误会明确报错。

```bash
# 1. 启动日常高频自动分流
uv run python -m inbox_agent.agent

# 2. 启动历史邮件沉淀整理
uv run python -m inbox_agent.history_agent
```
> 无凭据时自动降级为离线模式，并在本地生成 `preview_email.html` 预览。
