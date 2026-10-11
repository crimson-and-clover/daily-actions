"""
GLaDOS 自动签到与兑换配置
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

__all__ = [
    "CHECKIN_URL",
    "COOKIE_FILE",
    "COOKIES_GLADOS",
    "EXCHANGE_URL",
    "ORIGIN_URL",
    "REFERER_URL",
    "USER_AGENT",
    "validate_config",
]

# 环境变量与鉴权凭据
COOKIES_GLADOS = (os.getenv("COOKIES_GLADOS") or "").strip()


def validate_config() -> None:
    """运行前校验所有核心配置与环境变量"""
    if not COOKIES_GLADOS:
        print("❌ [GLaDOS 配置错误] 缺失 COOKIES_GLADOS 环境变量，请在 .env 或 GitHub Secrets 中配置", file=sys.stderr)
        sys.exit(1)


# 本地 Cookie 缓存路径
COOKIE_FILE = Path(__file__).resolve().parent / "glados_cookies.txt"

# 接口端点与网络配置
CHECKIN_URL = "https://glados.cloud/api/user/checkin"
EXCHANGE_URL = "https://glados.cloud/api/user/exchange"
REFERER_URL = "https://glados.cloud/console/checkin"
ORIGIN_URL = "https://glados.cloud"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
