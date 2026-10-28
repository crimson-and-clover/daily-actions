"""
Reviewer Radar 配置与监控目标定义
顶级学术会议与工作坊审稿机会感知雷达
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# 基础环境变量与外部服务密钥
GMAIL_USER = (os.getenv("GMAIL_USER") or "").strip()
GMAIL_APP_PASS = (os.getenv("GMAIL_APP_PASS") or "").replace(" ", "").strip()
NOTIFICATION_EMAIL = (os.getenv("NOTIFICATION_EMAIL") or "").strip() or GMAIL_USER
IS_CI = bool(os.getenv("CI"))
DEEPSEEK_API_KEY = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
OPENREVIEW_PROFILE_ID = (os.getenv("OPENREVIEW_PROFILE_ID") or "").strip()
OPENREVIEW_PROFILE_URL = (
    f"https://openreview.net/profile?id={OPENREVIEW_PROFILE_ID}"
    if OPENREVIEW_PROFILE_ID
    else ""
)
GOOGLE_SCHOLAR_URL = (os.getenv("GOOGLE_SCHOLAR_URL") or "").strip()

# 路径定位
CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CURRENT_DIR.parent.parent

# 状态持久化路径 (统一保存在 state/reviewer-radar)
STATE_DIR = REPO_ROOT / "state" / "reviewer-radar"
MEMORY_FILE = STATE_DIR / "history.json"

# 模板目录
TEMPLATES_HTML_DIR = CURRENT_DIR / "templates" / "html"
TEMPLATES_PROMPTS_DIR = CURRENT_DIR / "templates" / "prompts"


def validate_config() -> None:
    """运行前校验所有核心配置与环境变量"""
    errors = []
    if not DEEPSEEK_API_KEY:
        errors.append("未配置 DEEPSEEK_API_KEY，ReAct 自主智能体无法启动")
    if IS_CI:
        if not GMAIL_USER:
            errors.append("CI 环境中必须配置 GMAIL_USER 邮箱 Secrets")
        if not GMAIL_APP_PASS:
            errors.append("CI 环境中必须配置 GMAIL_APP_PASS 应用密码 Secrets")

    if errors:
        for err in errors:
            print(f"[ReviewerRadar 配置错误] {err}", file=sys.stderr)
        sys.exit(1)


# 可信表单与在线申请平台的 URL 特征白名单
FORM_DOMAINS = [
    "forms.gle",
    "docs.google.com/forms",
    "forms.office.com",
    "openreview.net/invitation",
    "openreview.net/group",
    "typeform.com",
    "qualtrics.com",
    "surveymonkey.com",
]

# 用户个人学术资质背景 (针对已发表顶会自荐)
USER_ACADEMIC_PROFILE = {
    "publications": ["CVPR (IEEE/CVF)", "ICCV (IEEE/CVF)"],
    "expertise": ["Computer Vision", "Generative Models", "Multimodal AI", "Perception"],
    "openreview_url": OPENREVIEW_PROFILE_URL,
    "scholar_url": GOOGLE_SCHOLAR_URL,
}
