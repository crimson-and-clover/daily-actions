"""
IMAP 交互模块封装
包含：
- models: Email 领域实体与 LabelSpec 标签规格 (UID 统一原生 int, 基于 Pydantic BaseModel)
- connection: ImapConnection 传输层连接 (Fail-Fast, 支持 Context Manager)
- labels: LABEL_SPECS 全局标签配置与 LabelService 原生 X-GM-LABELS 标签服务
- repo: MessageRepo 邮件检索与仓储 (Fail-Fast)
- flags: FlagService 标记管理
- drafts: DraftService 草稿服务
- parser: 现代化邮件报文与正文解析器 (基于 email policy.default)
- mutf7: RFC 3501 Modified UTF-7 编解码器
"""

from inbox_agent.imap.connection import ImapConnection
from inbox_agent.imap.drafts import DraftService
from inbox_agent.imap.flags import FlagService
from inbox_agent.imap.labels import LABEL_SPECS, LabelService
from inbox_agent.imap.models import Email, LabelSpec
from inbox_agent.imap.mutf7 import mutf7_decode, mutf7_encode
from inbox_agent.imap.parser import extract_unsubscribe_link, parse_email_message
from inbox_agent.imap.repo import MessageRepo

__all__ = [
    "LABEL_SPECS",
    "DraftService",
    "Email",
    "FlagService",
    "ImapConnection",
    "LabelService",
    "LabelSpec",
    "MessageRepo",
    "extract_unsubscribe_link",
    "mutf7_decode",
    "mutf7_encode",
    "parse_email_message",
]
