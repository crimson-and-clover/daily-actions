# 📬 Inbox Agent (收件箱智能整理助手)

基于 **Agentic ReAct (Reasoning + Acting) 工具调用架构** 与 **多轮决策** 的全自主邮件智能助手。全流程严格遵循 **「绝不物理删除」** 原则，所有废弃操作均移入 `[Gmail]/Trash` 回收站（支持原位找回）。

---

## 🌟 核心架构

1. **自主工具调用 (Tool-Calling / Function Calling)**：
   - 告别硬编码脚本流水线，赋予 Agent 专属邮件工具箱（`apply_labels`, `mark_email_flags`, `read_email_content`, `search_emails`, `create_calendar_event`, `list_calendar_events`, `remove_calendar_event`, `create_email_draft`）。
   - 细化多维度业务识别：验证码安全口令、银行证券动账账单、政务事务公函、商业推广、系统通知、日程待办与恶意垃圾。
   - 遇到疑难邮件自主调用 `read_email_content` 深读正文，提取会议议程、差旅机票及 DDL 待办。
2. **10 封独立上下文批次机制 (Fresh Context Batching)**：
   - 每次处理 10 封待办邮件（包括收件箱新信与垃圾箱复核），开启全新的对话上下文，根绝 Token 冗余膨胀与注意力衰减。
   - 每批次处理完毕即时将状态与加密记忆持久化（Fernet AES），容错率高。
3. **主动对账与防御加固 (Active Reconciliation & Guardrails)**：
   - 批次结束时主动对账未处置邮件并追加拦截催促，确立每封邮件去向。
   - 严格防御 Prompt 注入与参数畸形（如参数被错误解析为列表时的防御性规整）。
4. **模块化 IMAP 解耦架构**：
   - 底层 IMAP 操作解耦为 `inbox_agent.imap` 模块化子包（基于 `imapclient`，包含 `ImapConnection`, `MessageRepo`, `LabelService`, `FlagService`, `DraftService` 与纯净 `Email` 数据实体）。

---

## 🛠️ 工具集 (Tools Matrix)

| 工具名称 | 功能描述 |
| :--- | :--- |
| **`apply_labels`** | 统一原子标签操作：批量添加/移除标签（归档、分类、移入垃圾箱、从垃圾箱解救）并附带处置备忘 |
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
| **`history_agent.py`** | `.github/workflows/inbox-history-agent.yml` | 每日 03:25 (避峰) | **90天历史积压归档**：从最旧到较新按批次扫描超过 90 天的历史邮件，AI 研判后移入 Trash 或对应归档目录。 |

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

```bash
# 1. 启动日常高频自动分流
uv run python -m inbox_agent.agent

# 2. 启动历史邮件沉淀整理
uv run python -m inbox_agent.history_agent
```
> 无凭据时自动降级为离线模式，并在本地生成 `preview_email.html` 预览。
