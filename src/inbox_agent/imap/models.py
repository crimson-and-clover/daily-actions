"""
IMAP 领域数据模型定义
包含 LabelSpec 标签规格与 Email 邮件数据模型 (UID 统一为原生 int，基于 Pydantic BaseModel)
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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

    uid: int = 0
    message_id: str = ""
    subject: str = ""
    from_addr: str = ""
    to_addr: str = ""
    date: str = ""
    snippet: str = ""
    body: str = ""
    raw_html: str = ""
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    unsubscribe_link: str = ""
    labels: list[str] = Field(default_factory=list)
    codes: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典对象 (包含兼容字段 id)"""
        data = self.model_dump()
        data["id"] = self.uid
        return data
