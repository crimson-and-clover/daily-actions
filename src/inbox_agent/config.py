import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from utils.timezone import BJT, get_now_bjt

load_dotenv()

__all__ = [
    "BJT",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_TIMEOUT",
    "FETCH_DAYS_LIMIT",
    "GMAIL_APP_PASS",
    "GMAIL_USER",
    "INBOX_STATE_KEY",
    "IS_CI",
    "MAX_EMAILS_PER_RUN",
    "MEMORY_FILE",
    "NOTIFICATION_EMAIL",
    "PRUNE_DAYS",
    "TEMPLATES_HTML_DIR",
    "get_now_bjt",
    "validate_config",
]

# 环境变量与凭据配置
INBOX_STATE_KEY = (os.getenv("INBOX_STATE_KEY") or "").strip()
GMAIL_USER = (os.getenv("GMAIL_USER") or "").strip()
GMAIL_APP_PASS = (os.getenv("GMAIL_APP_PASS") or "").replace(" ", "").strip()
NOTIFICATION_EMAIL = (os.getenv("NOTIFICATION_EMAIL") or "").strip() or GMAIL_USER
DEEPSEEK_API_KEY = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
IS_CI = bool(os.getenv("CI"))


def validate_config(require_deepseek: bool = True) -> None:
    """运行前校验所有核心配置与环境变量"""
    errors = []
    if not GMAIL_USER:
        errors.append("缺少 GMAIL_USER 邮箱配置")
    if not GMAIL_APP_PASS:
        errors.append("缺少 GMAIL_APP_PASS 应用密码配置")
    if require_deepseek and not DEEPSEEK_API_KEY:
        errors.append("缺少 DEEPSEEK_API_KEY 大模型密钥配置")
    if not INBOX_STATE_KEY:
        if IS_CI:
            errors.append("CI 环境中必须配置 INBOX_STATE_KEY Secrets")
        else:
            print("[Security Warning] 本地未检测到 INBOX_STATE_KEY，状态将无法加密持久化", file=sys.stderr)

    if errors:
        for err in errors:
            print(f"❌ [Inbox Agent 配置错误] {err}", file=sys.stderr)
        sys.exit(1)


# 路径定位
CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CURRENT_DIR.parent.parent

# 状态与持久化路径 (统一存储于 state/inbox-agent，使用 Fernet 加密存储以保护公开仓库隐私)
MEMORY_FILE = REPO_ROOT / "state" / "inbox-agent" / "history.enc"

# 模板路径
TEMPLATES_HTML_DIR = CURRENT_DIR / "templates" / "html"

# 运行参数
FETCH_DAYS_LIMIT = 30  # 拉取近期邮件窗口 (支持回溯积压)
MAX_EMAILS_PER_RUN = 100  # 单次处理的最大邮件数量提升至 100 封，新到旧优先处理
PRUNE_DAYS = 90  # 自动清理 90 天以上的低价值/营销垃圾邮件

# DeepSeek 配置
DEEPSEEK_MODEL = "deepseek-flash"
DEEPSEEK_TIMEOUT = 30.0
