# 📬 Inbox Agent (收件箱智能整理助手)

收件箱自动分类整理与历史邮件归档系统。全流程严格遵循 **「绝不物理删除」** 原则，所有废弃操作均移入 `[Gmail]/Trash` 回收站（支持原位找回）。

---

## ⚙️ 组件构成与调度

| 组件脚本 | 对应工作流 | 调度周期 (北京时间) | 职能定义 |
| :--- | :--- | :--- | :--- |
| **`agent.py`** | `.github/workflows/inbox-agent.yml` | 每日 08:10 / 13:10 / 20:10 | **日常实时分流**：处理收件箱最新邮件，提炼日程待办与 DDL，将推广归档至 `商业推广`，通知归档至 `系统通知`，恶意垃圾移至 `[Gmail]/Spam`。 |
| **`history_agent.py`** | `.github/workflows/inbox-history-agent.yml` | 每日 03:25 (避峰) | **90天历史积压归档**：从最旧到较新按批次（每 10 封一小批）扫描超过 90 天的历史邮件，AI 研判后移入 Trash 或对应归档目录。 |

---

## 🔑 所需凭据 (GitHub Secrets)

| 变量名称 | 必需性 | 说明 |
| :--- | :---: | :--- |
| `GMAIL_USER` | **必需** | Gmail 账号（如 `user@gmail.com`） |
| `GMAIL_APP_PASS` | **必需** | Google 专用 16 位应用密码（非登录密码） |
| `DEEPSEEK_API_KEY` | **必需** | 用于邮件四维分类、日程提炼与历史研判的大模型密钥 |
| `INBOX_STATE_KEY` | **必需** | 收件箱记忆库 Fernet AES 对称加密密钥，保护邮件隐私与防重状态 |
| `NOTIFICATION_EMAIL`| 可选 | 汇总邮件接收地址（默认发送至 `GMAIL_USER`） |

### 生成加密密钥
运行仓库内置脚本即可生成 `INBOX_STATE_KEY`：
```bash
python scripts/generate_inbox_key.py
```

---

## 🚀 本地调试

```bash
# 日常高频分流
uv run python -m inbox_agent.agent

# 历史邮件沉淀整理
uv run python -m inbox_agent.history_agent
```
> 无凭据时自动降级为离线模式，并在本地生成 `preview_email.html` 预览。
