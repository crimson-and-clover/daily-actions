"""
配置与常量定义 (World News Intelligence Configuration)
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from utils.timezone import get_now_bjt

__all__ = [
    "ARCHIVES_DIR",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_TIMEOUT",
    "DEFAULT_MAX_RETRIES",
    "DOCS_DIR",
    "DOCS_ROOT",
    "FETCH_TIMEOUT",
    "GITHUB_SEARCH_DAYS",
    "GITHUB_SEARCH_LIMIT",
    "GITHUB_SEARCH_MIN_STARS",
    "GMAIL_APP_PASS",
    "GMAIL_USER",
    "HN_TOP_STORIES_LIMIT",
    "IS_CI",
    "MACRO_SOURCES",
    "MAX_NEWS_AGE_DAYS",
    "MEMORY_DIR",
    "MEMORY_FILE",
    "NOTIFICATION_EMAIL",
    "PAGES_BASE_URL",
    "PREVIEW_REPORT_PATH",
    "RETRY_BACKOFF_FACTOR",
    "SCORE_THRESHOLD",
    "TEMPLATES_HTML_DIR",
    "get_now_bjt",
    "validate_config",
]

load_dotenv()

# 凭据与 CI 标记配置
GMAIL_USER = (os.getenv("GMAIL_USER") or "").strip()
GMAIL_APP_PASS = (os.getenv("GMAIL_APP_PASS") or "").replace(" ", "").strip()
NOTIFICATION_EMAIL = (os.getenv("NOTIFICATION_EMAIL") or "").strip() or GMAIL_USER
IS_CI = bool(os.getenv("CI"))


def validate_config() -> None:
    """运行前校验所有核心配置与环境变量"""
    errors = []
    if not DEEPSEEK_API_KEY:
        errors.append("未配置 DEEPSEEK_API_KEY，全球内参多维评估研判必须配置大模型密钥")
    if IS_CI:
        if not GMAIL_USER:
            errors.append("CI 环境中必须配置 GMAIL_USER 邮箱 Secrets")
        if not GMAIL_APP_PASS:
            errors.append("CI 环境中必须配置 GMAIL_APP_PASS 应用密码 Secrets")

    if errors:
        for err in errors:
            print(f"❌ [World News 配置错误] {err}", file=sys.stderr)
        sys.exit(1)


# 路径定位
CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CURRENT_DIR.parent.parent

# 模板路径
TEMPLATES_HTML_DIR = CURRENT_DIR / "templates" / "html"

# 报告与静态页面路径
DOCS_ROOT = REPO_ROOT / "docs"
DOCS_DIR = DOCS_ROOT / "world-news"
ARCHIVES_DIR = DOCS_DIR / "archives"
PREVIEW_REPORT_PATH = CURRENT_DIR / "preview_report.html"

# 持久化状态路径
MEMORY_DIR = REPO_ROOT / "state" / "world-news"
MEMORY_FILE = MEMORY_DIR / "history.json"

# 服务与外部配置
PAGES_BASE_URL = os.getenv("PAGES_BASE_URL", "https://crimson-and-clover.github.io/daily-actions")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()

# 准入评分与时效阈值
SCORE_THRESHOLD = 7.0
MAX_NEWS_AGE_DAYS = 3

# 宏观与财经数据源配置
MACRO_SOURCES = [
    {"name": "WSJ World", "url": "https://feeds.content.dowjones.io/public/rss/RSSWorldNews", "limit": 10},
    {"name": "WSJ Markets", "url": "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain", "limit": 10},
    {"name": "Bloomberg Markets", "url": "https://feeds.bloomberg.com/markets/news.rss", "limit": 10},
    {"name": "CNBC Markets", "url": "https://www.cnbc.com/id/10000664/device/rss/rss.html", "limit": 10},
    {"name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "limit": 10},
]

# 科技与开源数据源配置
HN_TOP_STORIES_LIMIT = 15
GITHUB_SEARCH_DAYS = 35
GITHUB_SEARCH_MIN_STARS = 150
GITHUB_SEARCH_LIMIT = 8

# 网络请求与模型调用重试配置
DEFAULT_MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 2
FETCH_TIMEOUT = 12
DEEPSEEK_TIMEOUT = 85
DEEPSEEK_MODEL = "deepseek-flash"
