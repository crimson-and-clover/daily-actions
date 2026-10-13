"""
IMAP 领域数据模型定义
包含 LabelSpec 标签规格与 Email 邮件数据类 (UID 统一为原生 int)
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LabelSpec:
    """
    Gmail 标签规格

    Attributes:
        code: 英文业务代码（用于模型工具 enum 与代码分支，如 "promotions", "finance_banking"）
        label_name: 标签名称（传给 add_gmail_labels / remove_gmail_labels，如 "\\Inbox", "商业推广"）
        folder_name: 目录名称（传给 select_folder，如 "INBOX", "商业推广"）
    """

    code: str
    label_name: str
    folder_name: str


@dataclass(frozen=True)
class Email:
    """邮件领域模型实体 (UID 统一为原生 int)"""

    uid: int
    message_id: str
    subject: str
    from_addr: str
    to_addr: str
    date: str
    snippet: str
    body: str
    raw_html: str = ""
    attachments: list[dict[str, Any]] = field(default_factory=list)
    unsubscribe_link: str = ""
    folder: str = "INBOX"

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典对象"""
        return {
            "uid": self.uid,
            "id": self.uid,
            "message_id": self.message_id,
            "subject": self.subject,
            "from_addr": self.from_addr,
            "to_addr": self.to_addr,
            "date": self.date,
            "snippet": self.snippet,
            "body": self.body,
            "raw_html": self.raw_html,
            "attachments": self.attachments,
            "unsubscribe_link": self.unsubscribe_link,
            "folder": self.folder,
        }
