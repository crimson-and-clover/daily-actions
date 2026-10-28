"""
IMAP 领域数据模型定义
包含 LabelSpec 标签规格与 Email 邮件数据模型 (UID 统一为原生 int，基于 Pydantic BaseModel)
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

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


class EmailContentResult(BaseModel):
    """邮件完整详情模型 (Pydantic 严格校验与确定性序列化)"""

    model_config = ConfigDict(frozen=True)

    status: str = "success"
    uid: int
    code: str
    folder: str
    subject: str
    from_addr: str
    to_addr: str
    date: datetime
    message_id: str
    body: str
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    unsubscribe_link: str = ""
    truncated: bool = False

    @field_serializer("date", mode="plain")
    def _serialize_date(self, dt: datetime) -> str:
        """统一序列化为带 ISO 时区偏移的标准字符串，避免裸 DateTime 进入 json 序列化链路"""
        return parse_bjt_datetime(dt).format("YYYY-MM-DD HH:mmZ")


class Email(BaseModel):
    """邮件领域模型实体 (UID 统一为原生 int)"""

    model_config = ConfigDict(frozen=True)

    uid: int
    message_id: str
    subject: str
    from_addr: str
    to_addr: str
    date: datetime
    raw_date: str = ""
    date_parsed: bool = True
    snippet: str
    body: str
    raw_html: str = ""
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    unsubscribe_link: str = ""
    labels: list[str] = Field(default_factory=list)
    codes: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce_date_and_parsed(cls, data: Any) -> Any:
        if isinstance(data, dict) and "date" in data:
            raw_v = data.get("date")
            has_explicit_parsed = "date_parsed" in data
            if raw_v is None or raw_v == "":
                data["date"] = get_now_bjt()
                if not has_explicit_parsed:
                    data["date_parsed"] = False
            elif not isinstance(raw_v, datetime):
                try:
                    data["date"] = parse_bjt_datetime(raw_v)
                    if not has_explicit_parsed:
                        data["date_parsed"] = True
                except Exception:
                    data["date"] = get_now_bjt()
                    if not has_explicit_parsed:
                        data["date_parsed"] = False
        return data

    @field_serializer("date", mode="plain")
    def _serialize_date(self, dt: datetime) -> str:
        return self.date_str

    @property
    def date_str(self) -> str:
        """返回带 ISO 时区偏移量的格式化字符串，如 2026-10-27 15:30+08:00"""
        dt = parse_bjt_datetime(self.date)
        return dt.format("YYYY-MM-DD HH:mmZ")

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典对象 (包含兼容字段 id 与格式化 date 字符串)"""
        data = self.model_dump(mode="json")
        data["id"] = self.uid
        data["date"] = self.date_str
        return data
