"""
Market FX 配置、标的定义与全局路径
"""

import os
import sys
from pathlib import Path

from utils.timezone import get_now_bjt

__all__ = [
    "CURRENT_DIR",
    "DOCS_DIR",
    "DOCS_ROOT",
    "GMAIL_APP_PASS",
    "GMAIL_USER",
    "IS_CI",
    "MEMORY_DIR",
    "MEMORY_FILE",
    "NOTIFICATION_EMAIL",
    "PAGES_BASE_URL",
    "TEMPLATES_HTML_DIR",
    "TICKERS_CONFIG",
    "get_now_bjt",
    "validate_config",
]

# 凭据与 CI 标记配置
GMAIL_USER = (os.getenv("GMAIL_USER") or "").strip()
GMAIL_APP_PASS = (os.getenv("GMAIL_APP_PASS") or "").replace(" ", "").strip()
NOTIFICATION_EMAIL = (os.getenv("NOTIFICATION_EMAIL") or "").strip() or GMAIL_USER
IS_CI = bool(os.getenv("CI"))


def validate_config() -> None:
    """运行前校验所有核心配置与环境变量"""
    errors = []
    if IS_CI:
        if not GMAIL_USER:
            errors.append("CI 环境中必须配置 GMAIL_USER 邮箱 Secrets")
        if not GMAIL_APP_PASS:
            errors.append("CI 环境中必须配置 GMAIL_APP_PASS 应用密码 Secrets")

    if errors:
        for err in errors:
            print(f"❌ [Market FX 配置错误] {err}", file=sys.stderr)
        sys.exit(1)


# 路径定位
CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CURRENT_DIR.parent.parent

# 模板路径
TEMPLATES_HTML_DIR = CURRENT_DIR / "templates" / "html"

# 文档与静态发布目录 (GitHub Pages)
DOCS_ROOT = REPO_ROOT / "docs"
DOCS_DIR = DOCS_ROOT / "market-fx"
PAGES_BASE_URL = os.getenv("PAGES_BASE_URL", "https://crimson-and-clover.github.io/daily-actions")

# 持久化存储路径 (统一存储于 state/market-fx)
MEMORY_DIR = REPO_ROOT / "state" / "market-fx"
MEMORY_FILE = MEMORY_DIR / "history.json"

# 标的资产配置
TICKERS_CONFIG = {
    "fx_major": [
        {"symbol": "USDCNY=X", "name": "美元 / 人民币 (USD/CNY)", "scale": 1.0, "decimals": 4},
        {"symbol": "EURCNY=X", "name": "欧元 / 人民币 (EUR/CNY)", "scale": 1.0, "decimals": 4},
        {"symbol": "JPYCNY=X", "name": "100 日元 / 人民币 (JPY/CNY)", "scale": 100.0, "decimals": 4},
        {"symbol": "GBPCNY=X", "name": "英镑 / 人民币 (GBP/CNY)", "scale": 1.0, "decimals": 4},
        {"symbol": "HKDCNY=X", "name": "港币 / 人民币 (HKD/CNY)", "scale": 1.0, "decimals": 4},
    ],
    "fx_travel": [
        {"symbol": "AUDCNY=X", "name": "澳元 / 人民币 (AUD/CNY)", "scale": 1.0, "decimals": 4},
        {"symbol": "SGDCNY=X", "name": "新加坡元 / 人民币 (SGD/CNY)", "scale": 1.0, "decimals": 4},
    ],
    "commodities_macro": [
        {"symbol": "GC=F", "name": "COMEX 黄金期货 (Gold)", "scale": 1.0, "decimals": 2},
        {"symbol": "BTC-USD", "name": "比特币 (Bitcoin / BTC)", "scale": 1.0, "decimals": 2},
        {"symbol": "DX-Y.NYB", "name": "美元指数 (DXY)", "scale": 1.0, "decimals": 2},
        {"symbol": "^TNX", "name": "美债10年期收益率 (10Y Yield)", "scale": 1.0, "decimals": 2},
        {"symbol": "CL=F", "name": "WTI 原油期货 (Crude Oil)", "scale": 1.0, "decimals": 2},
    ],
    "indices": [
        {"symbol": "^GSPC", "name": "标普500 (S&P 500)", "scale": 1.0, "decimals": 2},
        {"symbol": "^IXIC", "name": "纳斯达克 (Nasdaq)", "scale": 1.0, "decimals": 2},
        {"symbol": "^DJI", "name": "道琼斯 (Dow Jones)", "scale": 1.0, "decimals": 2},
    ],
    "tech_stocks": [
        {"symbol": "NVDA", "name": "英伟达 (NVIDIA)", "scale": 1.0, "decimals": 2},
        {"symbol": "TSLA", "name": "特斯拉 (Tesla)", "scale": 1.0, "decimals": 2},
        {"symbol": "GOOGL", "name": "谷歌 (Alphabet)", "scale": 1.0, "decimals": 2},
        {"symbol": "AAPL", "name": "苹果 (Apple)", "scale": 1.0, "decimals": 2},
        {"symbol": "MSFT", "name": "微软 (Microsoft)", "scale": 1.0, "decimals": 2},
        {"symbol": "AMZN", "name": "亚马逊 (Amazon)", "scale": 1.0, "decimals": 2},
    ],
}
