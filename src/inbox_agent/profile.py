"""加载由用户维护的个人背景配置，供系统提示词判断邮件适用性。"""

from pathlib import Path

from pydantic import BaseModel, ConfigDict

DEFAULT_PROFILE_PATH = Path(__file__).resolve().parent / "user_profile.json"


class UserProfile(BaseModel):
    """个人事实、当前目标与处理偏好；不由邮件内容自动更新。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    facts: list[str]
    goals: list[str]
    preferences: list[str]


def load_user_profile(path: Path | str = DEFAULT_PROFILE_PATH) -> UserProfile:
    """每次构建系统提示词时读取配置；配置损坏时明确报错，不静默忽略。"""
    profile_path = Path(path)
    try:
        return UserProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"无法加载用户 profile，请检查文件是否存在且 facts、goals、preferences 均为字符串数组：{profile_path}") from exc
