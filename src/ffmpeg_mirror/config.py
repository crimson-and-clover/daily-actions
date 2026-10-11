"""
FFmpeg Mirror 同步配置与常量定义
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

__all__ = [
    "DOWNLOAD_URLS",
    "GITHUB_OUTPUT_FILE",
    "GITHUB_TOKEN",
    "REPO",
    "TAG_PREFIX",
    "validate_config",
]

# GitHub 环境与凭证
REPO = os.getenv("GITHUB_REPOSITORY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OUTPUT_FILE = Path(os.environ.get("GITHUB_OUTPUT", "local_output.txt"))


def validate_config() -> None:
    """运行前校验所有核心配置与环境变量"""
    errors = []
    if not REPO:
        errors.append("缺少 GITHUB_REPOSITORY 环境变量配置")
    if not GITHUB_TOKEN:
        errors.append("缺少 GITHUB_TOKEN 凭据配置")

    if errors:
        for err in errors:
            print(f"❌ [FFmpeg Mirror 配置错误] {err}", file=sys.stderr)
        sys.exit(1)


# 任务配置
TAG_PREFIX = "ffmpeg-win-"  # 过滤和创建标签的前缀

DOWNLOAD_URLS = [
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.7z",
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.7z",
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full-shared.7z",
]
