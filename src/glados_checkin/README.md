# 🛡️ GLaDOS Checkin (自动签到任务)

轻量级云服务状态与权益自动维护脚本。

---

## ⚙️ 核心职能

- 每日自动化调用 GLaDOS 鉴权接口完成签到与权益兑换，保障开发节点与代理账号续期活跃。
- **调度周期**：每日 **08:20 BJT** (`20 0 * * * UTC`)。

---

## 🔑 所需凭据 (GitHub Secrets)

| 变量名称 | 必需性 | 说明 |
| :--- | :---: | :--- |
| `COOKIES_GLADOS` | **必需** | GLaDOS 鉴权 Cookie (支持 Base64 编码或原始 Cookie 字符串) |

---

## 🚀 本地调试

```bash
uv run python -m glados_checkin.checkin
```
