"""
IMAP 领域数据模型定义
包含 LabelSpec 标签规格与 Email 邮件数据模型 (UID 统一为原生 int，基于 Pydantic BaseModel)
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from utils.timezone import get_now_bjt, parse_bjt_datetime


class LabelSpec(BaseModel):
    """
    Gmail 标签规格

    Attributes:
        code: 英文业务代码（用于模型工具 enum 与代码分支，如 "promotions", "finance_banking"）
        label_name: 标签名称（传给 add_gmail_labels / remove_gmail_labels，如 "\\Inbox", "商业推广"）
        folder_name: 目录名称（传给 select_folder，如 "INBOX", "商业推广"）
    """

    model_config = ConfigDict(frozen=True)

    code: str
    label_name: str
    folder_name: str


class Email(BaseModel):
    """邮件领域模型实体 (UID 统一为原生 int)"""

    model_config = ConfigDict(frozen=True)

    uid: int
    message_id: str
    subject: str
    from_addr: str
    to_addr: str
    date: datetime
    snippet: str
    body: str
    raw_html: str = ""
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    unsubscribe_link: str = ""
    labels: list[str] = Field(default_factory=list)
    codes: list[str] = Field(default_factory=list)

    @field_validator("date", mode="before")
    @classmethod
    def _coerce_date(cls, v: Any) -> datetime:
        if v is None or v == "":
            return get_now_bjt()
        try:
            return parse_bjt_datetime(v, fallback=get_now_bjt())
        except Exception:
            return get_now_bjt()

    @property
    def date_str(self) -> str:
        """返回带 ISO 时区偏移量的格式化字符串，如 2026-10-27 15:30+08:00"""
        dt = parse_bjt_datetime(self.date)
        return dt.format("YYYY-MM-DD HH:mmZ")

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典对象 (包含兼容字段 id 与格式化 date 字符串)"""
        data = self.model_dump()
        data["id"] = self.uid
        data["date"] = self.date_str
        return data
