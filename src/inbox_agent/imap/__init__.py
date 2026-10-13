"""
IMAP 交互模块封装
包含：
- mutf7: RFC 3501 Modified UTF-7 编解码器
- parser: 邮件头、正文、HTML、附件及退订链接解析工具
- client: GmailClient IMAP 交互客户端
"""

from inbox_agent.imap.client import GmailClient
from inbox_agent.imap.mutf7 import mutf7_decode, mutf7_encode
from inbox_agent.imap.parser import (
    decode_str,
    extract_email_body,
    extract_email_body_and_html,
    extract_unsubscribe_link,
    parse_folder_name_from_list_line,
)

__all__ = [
    "GmailClient",
    "decode_str",
    "extract_email_body",
    "extract_email_body_and_html",
    "extract_unsubscribe_link",
    "mutf7_decode",
    "mutf7_encode",
    "parse_folder_name_from_list_line",
]
