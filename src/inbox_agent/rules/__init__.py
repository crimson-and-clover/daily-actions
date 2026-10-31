"""
收件箱规则引擎配置与加载器
负责加载和维护内部 CI 邮件过滤规则等 JSON 配置文件
"""

import json
from email.utils import parseaddr
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

DEFAULT_RULES_PATH = Path(__file__).resolve().parent / "internal_ci_rules.json"


class InternalCIRules(BaseModel):
    """内部自动化/CI 邮件过滤判定规则模型"""

    subject_prefixes: list[str] = Field(
        default_factory=lambda: [
            "[Inbox Agent]",
            "[Paper Agent]",
            "[Market FX]",
            "[World News]",
            "[Reviewer Radar]",
        ]
    )


@lru_cache(maxsize=1)
def load_internal_ci_rules(config_path: Path | str | None = None) -> InternalCIRules:
    """加载内部 CI 邮件识别规则配置 (带单例缓存与安全回退)"""
    target_path = Path(config_path) if config_path else DEFAULT_RULES_PATH
    if not target_path.exists():
        return InternalCIRules()

    try:
        with open(target_path, encoding="utf-8") as f:
            raw_data: dict[str, Any] = json.load(f)
        return InternalCIRules.model_validate(raw_data)
    except Exception as e:
        print(f"[Rules Warning] 加载内部 CI 规则配置失败 ({target_path}): {e}，将采用默认防御规则")
        return InternalCIRules()


def is_internal_ci(
    subject: str,
    sender: str = "",
    my_email: str = "",
    rules: InternalCIRules | None = None,
) -> bool:
    """
    判断邮件是否属于系统自发的 CI / 自动化简报邮件

    判定逻辑：
    1. 主题必须以系统自动化组件的前缀标签（如 [Inbox Agent]、[Paper Agent] 等）开头；
    2. 安全防伪造校验：若提供了发件人与配置的自身邮箱，必须核验发件人真实地址为自身邮箱，
       严防外部仿冒前缀导致重要邮件被静默吞掉。
    """
    if rules is None:
        rules = load_internal_ci_rules()

    clean_subject = (subject or "").strip().lower()
    if not any(clean_subject.startswith(p.strip().lower()) for p in rules.subject_prefixes):
        return False

    if my_email and sender:
        sender_addr = parseaddr(sender)[1].strip().lower()
        my_addr = my_email.strip().lower()
        if sender_addr != my_addr:
            return False

    return True
