"""
邮件内容解析与提取工具函数 (Parser)
利用现代 Python email (policy.default) 与 BeautifulSoup 自动处理 RFC 2047 解码、正文提取、HTML 清洗与附件解析
"""

import email
import re
from email import policy
from typing import Any

from bs4 import BeautifulSoup

from utils.timezone import get_now_bjt, parse_bjt_datetime


def extract_unsubscribe_link(msg: email.message.EmailMessage, raw_html: str = "") -> str:
    """提取邮件中的一键退订链接 (支持 RFC 2369 List-Unsubscribe 头部以及正文 HTML 链接)"""
    list_unsub = str(msg.get("List-Unsubscribe", ""))
    if list_unsub:
        urls = re.findall(r"<https?://[^>]+>", list_unsub)
        if urls:
            return urls[0].strip("<>")

    if raw_html:
        soup = BeautifulSoup(raw_html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = a.get_text().lower()
            href_lower = href.lower()
            if any(
                kw in text or kw in href_lower
                for kw in ["退订", "unsubscribe", "opt-out", "optout", "取消订阅"]
            ):
                return href

        direct_urls = re.findall(
            r'https?://[^\s"\'<>]+(?:unsubscribe|unsub|optout)[^\s"\'<>]*',
            raw_html,
            flags=re.IGNORECASE,
        )
        if direct_urls:
            return direct_urls[0]

    return ""


def parse_email_message(raw_bytes: bytes) -> dict[str, Any]:
    """基于 modern email policy 与 BeautifulSoup 解析原始邮件报文，返回结构化字典"""
    msg = email.message_from_bytes(raw_bytes, policy=policy.default)

    subject = str(msg["Subject"] or "无主题")
    from_addr = str(msg["From"] or "未知发件人")
    to_addr = str(msg["To"] or "")
    raw_date = msg.get("Date")
    date_val = parse_bjt_datetime(raw_date) if raw_date else get_now_bjt()
    message_id = str(msg["Message-ID"] or "").strip()

    body_text = ""
    raw_html = ""

    body_part = msg.get_body(preferencelist=("plain",))
    if body_part:
        try:
            body_text = body_part.get_content()
        except Exception:
            body_text = ""

    html_part = msg.get_body(preferencelist=("html",))
    if html_part:
        try:
            raw_html = html_part.get_content()
        except Exception:
            raw_html = ""

    # 单体非 multipart 邮件降级兼容
    if not body_text and not raw_html:
        main_type = msg.get_content_type()
        try:
            content = msg.get_content()
            if main_type == "text/html":
                raw_html = content
            elif main_type == "text/plain":
                body_text = content
        except Exception:
            pass

    if not body_text and raw_html:
        soup = BeautifulSoup(raw_html, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        body_text = soup.get_text(separator="\n", strip=True)

    attachments: list[dict[str, Any]] = []
    for att in msg.iter_attachments():
        fname = att.get_filename() or "untitled"
        payload = att.get_payload(decode=True) or b""
        attachments.append({
            "filename": fname,
            "content_type": att.get_content_type(),
            "size_bytes": len(payload),
        })

    unsub_link = extract_unsubscribe_link(msg, raw_html)

    return {
        "subject": subject,
        "from_addr": from_addr,
        "to_addr": to_addr,
        "date": date_val,
        "message_id": message_id,
        "body": body_text,
        "raw_html": raw_html,
        "attachments": attachments,
        "unsubscribe_link": unsub_link,
    }
