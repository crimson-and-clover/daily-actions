# 🤖 Paper Agent (AI 论文追踪助手)

前沿人工智能学术论文追踪系统。自动拉取最新预印本，通过两阶段大模型初筛与精读筛选高质量学术进展，提取核心方法架构图并探测官方存活开源代码。

---

## ⚙️ 核心机制与赛道

- **8 大前沿赛道**：测试期训练 (TTT/Scaling)、后训练强化学习与可解释性 (RLHF/DPO/SAE)、流匹配与视频生成 (Flow Matching/Video Gen)、大模型长上下文与推理、世界模型 (World Models)、具身智能 (VLA)、端到端自动驾驶、自动驾驶感知算法 (3D/BEV/Occupancy)。
- **两阶段过滤**：Abstract 粗筛 + HTML 全文多轮精研，淘汰浅层套壳水文。
- **架构图与官方开源**：自动抓取架构全景图（Key Figures），校验唯一存活的官方真实 GitHub 仓库。
- **去重与状态**：双向同步 `state/paper-agent` 分支长期记忆库。

---

## 🔑 所需凭据 (GitHub Secrets)

| 变量名称 | 必需性 | 说明 |
| :--- | :---: | :--- |
| `GMAIL_USER` | **必需** | Gmail 发信主账号 |
| `GMAIL_APP_PASS` | **必需** | Google 专用 16 位应用密码 |
| `DEEPSEEK_API_KEY` | **必需** | 驱动两阶段学术研判与打分的大模型密钥 |
| `NOTIFICATION_EMAIL`| 可选 | 接收研报的目标邮箱（默认发送至 `GMAIL_USER`） |

---

## 🚀 本地调试

```bash
uv run python -m paper_agent.agent
```
> 本地无邮件凭据时，研报将自动生成并保存至 `docs/paper-agent/index.html`。
