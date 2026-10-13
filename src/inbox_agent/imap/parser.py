"""
邮件内容解析与提取工具函数 (Parser)
负责 RFC 2047 头部解码、正文清洗、HTML 解析与退订链接提取
"""

import email.message
import re
from email.header import decode_header


def decode_str(header_val: str) -> str:
    """解码邮件主题与发件人等 RFC 2047 头部"""
    if not header_val:
        return ""
    try:
        decoded_seq = decode_header(header_val)
        parts = []
        for content, enc in decoded_seq:
            if isinstance(content, bytes):
                parts.append(content.decode(enc or "utf-8", errors="ignore"))
            else:
                parts.append(str(content))
        return "".join(parts).strip()
    except Exception:
        return str(header_val).strip()


def parse_folder_name_from_list_line(line: bytes | str) -> tuple[str, str]:
    """
    解析 imap.list() 返回的单行，提取 flags 和 folder_name。
    RFC 3501 LIST 格式形如: (\\HasNoChildren \\Spam) "/" "[Gmail]/&V4NXPpCu-" 或 (\\HasNoChildren) "/" INBOX
    返回: (flags_str, folder_name)
    """
    if isinstance(line, bytes):
        raw_str = line.decode("utf-8", errors="ignore")
    else:
        raw_str = str(line)

    flags = ""
    rest = raw_str.strip()
    flags_match = re.search(r"\(([^)]*)\)\s+(.*)$", rest)
    if flags_match:
        flags = flags_match.group(1)
        rest = flags_match.group(2).strip()

    mailbox_match = re.search(r'(?:"([^"]+)"|(\S+))\s*$', rest)
    if mailbox_match:
        folder_name = mailbox_match.group(1) if mailbox_match.group(1) is not None else (mailbox_match.group(2) or "")
    else:
        folder_name = rest.split()[-1] if rest else ""

    return flags, folder_name


def extract_unsubscribe_link(msg: email.message.Message, raw_html: str = "") -> str:
    """提取邮件中的一键退订链接 (支持 RFC 2369 List-Unsubscribe 头部以及正文 HTML 链接)"""
    list_unsub = msg.get("List-Unsubscribe", "")
    if list_unsub:
        urls = re.findall(r"<https?://[^>]+>", list_unsub)
        if urls:
            return urls[0].strip("<>")

    if raw_html:
        matches = re.findall(
            r'<a[^>]+href=["\'](https?://[^"\']+)["\'][^>]*>([\s\S]*?)</a>',
            raw_html,
            flags=re.IGNORECASE,
        )
        for link, text in matches:
            text_lower = text.lower()
            link_lower = link.lower()
            if any(
                kw in text_lower or kw in link_lower
                for kw in ["退订", "unsubscribe", "opt-out", "optout", "取消订阅"]
            ):
                return link

        direct_urls = re.findall(
            r'https?://[^\s"\'<>]+(?:unsubscribe|unsub|optout)[^\s"\'<>]*',
            raw_html,
            flags=re.IGNORECASE,
        )
        if direct_urls:
            return direct_urls[0]

    return ""


def extract_email_body_and_html(msg: email.message.Message) -> tuple[str, str]:
    """提取邮件的纯文本正文与原始 HTML"""
    text_body = ""
    html_body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdisp = str(part.get("Content-Disposition"))
            if ctype == "text/plain" and not text_body and "attachment" not in cdisp:
                payload = part.get_payload(decode=True)
                if payload:
                    text_body = payload.decode(
                        part.get_content_charset() or "utf-8", errors="ignore"
                    )
            elif ctype == "text/html" and not html_body and "attachment" not in cdisp:
                payload = part.get_payload(decode=True)
                if payload:
                    html_body = payload.decode(
                        part.get_content_charset() or "utf-8", errors="ignore"
                    )
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            decoded = payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")
            if msg.get_content_type() == "text/html":
                html_body = decoded
            else:
                text_body = decoded

    raw_source = text_body if text_body else html_body
    cleaned = re.sub(r"<style[\s\S]*?</style>", "", raw_source, flags=re.IGNORECASE)
    cleaned = re.sub(r"<script[\s\S]*?</script>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:6000], html_body


def extract_email_body(msg: email.message.Message) -> str:
    """提取纯文本格式的清洗后正文内容"""
    cleaned, _ = extract_email_body_and_html(msg)
    return cleaned
