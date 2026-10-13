# 📬 Inbox Agent (收件箱智能整理助手)

基于 **Agentic ReAct (Reasoning + Acting) 工具调用架构** 与 **多轮决策** 的全自主邮件智能助手。全流程严格遵循 **「绝不物理删除」** 原则，所有废弃操作均移入 `[Gmail]/Trash` 回收站（支持原位找回）。

---

## 🌟 核心架构升级

1. **自主工具调用 (Tool-Calling / Function Calling)**：
   - 告别硬编码脚本流水线，赋予 Agent 专属邮件工具箱（`move_emails`, `read_email_content`, `create_calendar_event`, `create_draft`, `search_emails`, `save_user_preference`, `rescue_from_spam`）。
   - 遇到疑难邮件自主调用 `read_email_content` 深读正文，提取会议议程、差旅机票及 DDL 待办。
2. **10 封独立上下文批次机制 (Fresh Context Batching)**：
   - 每次处理 10 封待办邮件，开启全新的对话上下文，根绝 Token 冗余膨胀与注意力衰减。
   - 每批次处理完毕即时将状态与加密记忆持久化（Fernet AES），容错率高。
3. **长期记忆与用户偏好沉淀 (Preference Learning)**：
   - 支持动态记录用户习惯（如：*某域名通知一律归档并标已读*），在后续批次与日常巡检中自动继承并优先遵循。
4. **双运行模式**：
   - **日常自动巡检**：定时高频分流收件箱新邮件与复核垃圾箱误杀。
   - **交互式多轮对话 (CLI Chat Mode)**：支持与 Agent 自然语言对话，按需搜索邮件、读信、建日程与拟定草稿。

---

## 🛠️ 工具集 (Tools Matrix)

| 工具名称 | 功能描述 |
| :--- | :--- |
| **`move_emails`** | 批量移动邮件至目标文件夹（商业推广、系统通知、Spam 垃圾箱、Trash 回收站） |
| **`read_email_content`** | 按 UID 深度抓取单封邮件完整正文与附件信息（按需调用，节省 Token） |
| **`mark_email_flags`** | 标记邮件已读/未读状态，或添加星标置顶重要邮件并留在 INBOX |
| **`create_calendar_event`** | 提取会议、出行及到期日 (DDL)，自动沉淀到待办日历池 |
| **`create_draft`** | 在 Gmail 草稿箱拟定回复或新信（遵循安全原则，绝不未经确认直发邮件） |
| **`search_emails`** | 交互对话中按关键词、发件人、日期或未读状态搜索邮件 |
| **`save_user_preference`** | 持久化用户的处理规则与偏好习惯，跨批次自动生效 |
| **`list_user_preferences`** | 查看当前已保存的所有用户偏好规则列表 |
| **`rescue_from_spam`** | 将 Google 误杀进 Spam 垃圾箱的邮件安全捞回收件箱或对应分类 |

---

## ⚙️ 组件构成与调度

| 组件脚本 | 对应工作流 | 调度周期 (北京时间) | 职能定义 |
| :--- | :--- | :--- | :--- |
| **`agent.py`** | `.github/workflows/inbox-agent.yml` | 每日 08:10 / 13:10 / 20:10 | **日常实时分流**：10 封一组 ReAct 决策，提炼日程待办与 DDL，将推广归档至 `商业推广`，通知归档至 `系统通知`，恶意垃圾移至 `[Gmail]/Spam`。 |
| **`agent.py --chat`** 或 **`chat.py`** | 本地交互 | 手动执行 | **多轮对话交互助手**：自然语言对话式查信、读信、拟定草稿与管理偏好。 |
| **`history_agent.py`** | `.github/workflows/inbox-history-agent.yml` | 每日 03:25 (避峰) | **90天历史积压归档**：从最旧到较新按批次扫描超过 90 天的历史邮件，AI 研判后移入 Trash 或对应归档目录。 |

---

## 🔑 所需凭据 (GitHub Secrets)

| 变量名称 | 必需性 | 说明 |
| :--- | :--- :--- | :--- |
| `GMAIL_USER` | **必需** | Gmail 账号（如 `user@gmail.com`） |
| `GMAIL_APP_PASS` | **必需** | Google 专用 16 位应用密码（非登录密码） |
| `DEEPSEEK_API_KEY` | **必需** | 用于邮件多轮决策、日程提炼与工具调用的模型密钥 |
| `INBOX_STATE_KEY` | **必需** | 收件箱记忆库 Fernet AES 对称加密密钥，保护邮件隐私与偏好规则 |
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

# 2. 启动交互式多轮对话助手 (CLI Chat)
uv run python -m inbox_agent.agent --chat
# 或
uv run python -m inbox_agent.chat

# 3. 历史邮件沉淀整理
uv run python -m inbox_agent.history_agent
```
> 无凭据时自动降级为离线模式，并在本地生成 `preview_email.html` 预览。
