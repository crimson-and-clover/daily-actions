# 🚀 FFmpeg Mirror (上游构建自动同步与分发)

监控并镜像上游高质量 FFmpeg 预构建资产的自动化任务。

---

## ⚙️ 核心职能

- 轮询 gyan.dev 最新 FFmpeg 二进制发行版本；
- 比对版本差异，有更新时自动下载打包，作为 GitHub Release 资产分发。
- **调度周期**：每周日 **10:15 BJT** (`15 2 * * 0 UTC`)。

---

## 🔑 所需凭据 (GitHub Secrets)

- **无需额外外部凭据**，依赖 GitHub Actions 默认分配的 `GITHUB_TOKEN`（需确保 Workflow 具备 Read and write permissions）。

---

## 🚀 本地调试

```bash
uv run python -m ffmpeg_mirror.sync_ffmpeg
```
