# 🌐 World News (全球宏观资讯与情报内参)

多源聚合全球宏观经济、资本市场与开源生态的综合情报内参系统。

---

## ⚙️ 核心聚合与研判机制

- **情报源矩阵**：CNBC Markets、WSJ World、BBC World、Hacker News、GitHub Trending。
- **冲击评分过滤**：基于 LLM 对信息施行 Impact Score (>= 7.0/10) 严格降噪，过滤无价值噱头与低信号碎片。
- **跨市场逻辑传导**：研判大宗商品、汇率与技术突破背后的产业纵深影响。
- **调度周期**：每日 **07:35 BJT** (`35 23 * * * UTC`)。

---

## 🔑 所需凭据 (GitHub Secrets)

| 变量名称 | 必需性 | 说明 |
| :--- | :---: | :--- |
| `GMAIL_USER` | **必需** | Gmail 发信主账号 |
| `GMAIL_APP_PASS` | **必需** | Google 专用 16 位应用密码 |
| `DEEPSEEK_API_KEY` | **必需** | 资讯提炼与量化冲击打分的大模型密钥 |
| `NOTIFICATION_EMAIL`| 可选 | 接收研报的目标邮箱（默认发送至 `GMAIL_USER`） |

---

## 🚀 本地调试

```bash
uv run python -m world_news.report
```
> 无凭据时自动降级输出至本地预览文件。
