"""
Inbox Agent 邮箱交互客户端 (IMAP) 兼容转发层
核心逻辑已拆分至 `inbox_agent.imap` 模块化子包：
- `inbox_agent.imap.mutf7`: RFC 3501 Modified UTF-7 编解码器
- `inbox_agent.imap.parser`: 邮件头部、正文、附件与退订链接提取
- `inbox_agent.imap.client`: GmailClient IMAP 连接与交互客户端
"""

from inbox_agent.imap import (
    GmailClient,
    decode_str,
    extract_email_body,
    extract_email_body_and_html,
    extract_unsubscribe_link,
    mutf7_decode,
    mutf7_encode,
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
