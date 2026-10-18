"""
Reviewer Radar 配置与监控目标定义
针对 NIW 绿卡申请的高质量顶会/顶刊审稿机会雷达
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

# 路径定位
CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CURRENT_DIR.parent.parent

# 状态持久化路径 (统一保存在 state/reviewer-radar)
STATE_DIR = REPO_ROOT / "state" / "reviewer-radar"
MEMORY_FILE = STATE_DIR / "history.json"

# HTML 模板目录
TEMPLATES_HTML_DIR = CURRENT_DIR / "templates" / "html"


def validate_config() -> None:
    """运行前校验所有核心配置与环境变量"""
    errors = []
    if not DEEPSEEK_API_KEY:
        errors.append("未配置 DEEPSEEK_API_KEY，审稿招募语义分析与自荐信生成需要大模型密钥")
    if IS_CI:
        if not GMAIL_USER:
            errors.append("CI 环境中必须配置 GMAIL_USER 邮箱 Secrets")
        if not GMAIL_APP_PASS:
            errors.append("CI 环境中必须配置 GMAIL_APP_PASS 应用密码 Secrets")

    if errors:
        for err in errors:
            print(f"❌ [Reviewer Radar 配置错误] {err}", file=sys.stderr)
        sys.exit(1)


# 重点关注的 7 大顶级学术会议 (CCF-A 级 & 同等顶级 AI/CV 会议)
TARGET_CONFERENCES = [
    {
        "short_name": "CVPR",
        "full_name": "IEEE/CVF Conference on Computer Vision and Pattern Recognition",
        "tier": "CCF-A / 顶会 (计算机视觉最高峰)",
        "official_url": "https://cvpr.thecvf.com",
        "openreview_prefix": "thecvf.com/CVPR",
        "primary_track": "Computer Vision, Multimodal, Generative AI",
    },
    {
        "short_name": "ICCV",
        "full_name": "IEEE/CVF International Conference on Computer Vision",
        "tier": "CCF-A / 顶会 (计算机视觉顶级双年盛会)",
        "official_url": "https://iccv.thecvf.com",
        "openreview_prefix": "thecvf.com/ICCV",
        "primary_track": "Computer Vision, Deep Learning",
    },
    {
        "short_name": "ECCV",
        "full_name": "European Conference on Computer Vision",
        "tier": "顶会 (欧洲计算机视觉顶级双年盛会)",
        "official_url": "https://www.ecva.net",
        "openreview_prefix": "ecva.net/ECCV",
        "primary_track": "Computer Vision, AI Perception",
    },
    {
        "short_name": "NeurIPS",
        "full_name": "Conference on Neural Information Processing Systems",
        "tier": "CCF-A / 顶会 (机器学习/深度学习顶级盛会)",
        "official_url": "https://neurips.cc",
        "openreview_prefix": "NeurIPS.cc",
        "primary_track": "Deep Learning, Multimodal, Generative Models, Vision",
    },
    {
        "short_name": "ICLR",
        "full_name": "International Conference on Learning Representations",
        "tier": "顶级盛会 (深度学习核心代表顶会)",
        "official_url": "https://iclr.cc",
        "openreview_prefix": "ICLR.cc",
        "primary_track": "Representation Learning, Deep Learning, Vision Models",
    },
    {
        "short_name": "ICML",
        "full_name": "International Conference on Machine Learning",
        "tier": "CCF-A / 顶会 (机器学习顶尖学术会议)",
        "official_url": "https://icml.cc",
        "openreview_prefix": "ICML.cc",
        "primary_track": "Machine Learning, Deep Learning, Vision & Language",
    },
    {
        "short_name": "AAAI",
        "full_name": "AAAI Conference on Artificial Intelligence",
        "tier": "CCF-A / 顶会 (综合性人工智能顶级会议)",
        "official_url": "https://aaai.org/conference/aaai/",
        "openreview_prefix": "AAAI.org",
        "primary_track": "Computer Vision, Artificial Intelligence, Machine Learning",
    },
]

# 用于匹配招募表单与紧急救火的关键特征词
RECRUITMENT_KEYWORDS = [
    "call for reviewers",
    "call for reviewer",
    "reviewer recruitment",
    "reviewer volunteer",
    "volunteer reviewer",
    "emergency reviewer",
    "emergency reviewers",
    "reviewer application",
    "become a reviewer",
    "seeking reviewers",
    "reviewer sign up",
    "reviewer registration",
]

# 外部问卷/表单平台的 URL 特征
FORM_DOMAINS = [
    "forms.gle",
    "docs.google.com/forms",
    "forms.office.com",
    "openreview.net/invitation",
    "openreview.net/group",
]

# 用户个人学术资质背景 (针对已发表 ICCV / CVPR)
USER_ACADEMIC_PROFILE = {
    "publications": ["CVPR (IEEE/CVF)", "ICCV (IEEE/CVF)"],
    "expertise": [
        "Computer Vision",
        "Deep Learning",
        "Image/Video Understanding",
        "Multimodal AI",
        "Generative Models",
    ],
    "target_goal": "NIW (National Interest Waiver) - Accumulate 3 High-Quality Peer Reviews",
}
