"""
邮件数据仓储层 (MessageRepo)
负责邮件的统一抓取、全文检索与正文/附件结构化解析 (UID 统一为原生 int，Fail-Fast)
"""

import email
from collections.abc import Callable
from email import policy
from typing import Any

from imapclient.imap_utf7 import decode as utf7_decode

from inbox_agent.imap.connection import ImapConnection
from inbox_agent.imap.labels import LABEL_SPECS, labels_to_codes
from inbox_agent.imap.models import Email
from inbox_agent.imap.parser import parse_email_message


class MessageRepo:
    """邮件检索与读取仓储实现"""

    def __init__(self, connection: ImapConnection):
        self.connection = connection

    def fetch_emails(
        self,
        code: str = "inbox",
        criteria: Any = "ALL",
        limit: int = 100,
        reverse: bool = True,
        is_processed_func: Callable[[str], bool] | None = None,
    ) -> list[Email]:
        """统一拉取邮件并封装为 Email 实体列表，任何阶段故障均 Fail-Fast 抛出异常"""
        folder = LABEL_SPECS[code].folder_name if code in LABEL_SPECS else code
        self.connection.select_folder(folder)

        client = self.connection.client
        uids: list[int] = client.search(criteria)
        if not uids:
            return []

        selected_uids = list(reversed(uids)) if reverse else list(uids)
        emails: list[Email] = []

        for uid in selected_uids:
            if len(emails) >= limit:
                break

            # 1. 优先仅抓取 Header 中的 Message-ID，用于跳过已处理邮件，避免全量下载
            header_data = client.fetch([uid], [b"BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]"])
            message_id = ""
            if header_data and uid in header_data:
                raw_hdr = header_data[uid].get(b"BODY[HEADER.FIELDS (MESSAGE-ID)]", b"")
                parsed_hdr = email.message_from_bytes(raw_hdr, policy=policy.default)
                message_id = str(parsed_hdr.get("Message-ID") or "").strip()

            if message_id and is_processed_func and is_processed_func(message_id):
                continue

            # 2. 抓取完整邮件报文与 Gmail 原生标签，失败直接 Fail-Fast
            full_fetch = client.fetch([uid], [b"RFC822", b"X-GM-LABELS"])
            if not full_fetch or uid not in full_fetch:
                raise RuntimeError(f"未能抓取 UID {uid} 的 RFC822 完整报文")

            raw_email_bytes = full_fetch[uid].get(b"RFC822", b"")
            if not raw_email_bytes:
                raise RuntimeError(f"UID {uid} 的 RFC822 报文内容为空")

            parsed = parse_email_message(raw_email_bytes)

            raw_labels = full_fetch[uid].get(b"X-GM-LABELS", ())
            labels: list[str] = [
                utf7_decode(lbl) if isinstance(lbl, bytes) else str(lbl)
                for lbl in raw_labels
            ]
            current_spec = LABEL_SPECS.get(code)
            if current_spec and current_spec.label_name not in labels:
                labels.insert(0, current_spec.label_name)

            codes = labels_to_codes(labels)
            if current_spec and current_spec.code not in codes:
                codes.insert(0, current_spec.code)

            emails.append(
                Email(
                    uid=uid,
                    message_id=message_id or parsed["message_id"],
                    subject=parsed["subject"],
                    from_addr=parsed["from_addr"],
                    to_addr=parsed["to_addr"],
                    date=parsed["date"],
                    snippet=parsed["body"][:1000],
                    body=parsed["body"],
                    raw_html=parsed["raw_html"],
                    attachments=parsed["attachments"],
                    unsubscribe_link=parsed["unsubscribe_link"],
                    labels=labels,
                    codes=codes,
                )
            )

        return emails

    def read_email_content(
        self,
        email_uid: int,
        code: str = "inbox",
        max_length: int = 4000,
    ) -> dict[str, Any]:
        """按 UID 读取单封邮件的完整正文及附件信息 (Fail-Fast)"""
        folder = LABEL_SPECS[code].folder_name if code in LABEL_SPECS else code
        self.connection.select_folder(folder)

        client = self.connection.client
        fetch_data = client.fetch([email_uid], [b"RFC822"])
        if not fetch_data or email_uid not in fetch_data:
            raise KeyError(f"在目录 {folder} 中未找到 UID 为 {email_uid} 的邮件")

        raw_bytes = fetch_data[email_uid].get(b"RFC822", b"")
        if not raw_bytes:
            raise ValueError(f"UID 为 {email_uid} 的邮件内容为空")

        parsed = parse_email_message(raw_bytes)

        body_text = parsed["body"]
        truncated = False
        if len(body_text) > max_length:
            body_text = (
                body_text[:max_length]
                + f"\n\n[正文已截断，总长度 {len(body_text)} 字符]"
            )
            truncated = True

        return {
            "status": "success",
            "uid": email_uid,
            "code": code,
            "folder": folder,
            "subject": parsed["subject"],
            "from_addr": parsed["from_addr"],
            "to_addr": parsed["to_addr"],
            "date": parsed["date"],
            "message_id": parsed["message_id"],
            "body": body_text,
            "attachments": parsed["attachments"],
            "unsubscribe_link": parsed["unsubscribe_link"],
            "truncated": truncated,
        }

    def get_email_by_message_id(
        self,
        message_id: str,
        code: str = "inbox",
        max_length: int = 4000,
    ) -> dict[str, Any] | None:
        """根据 RFC 822 Message-ID 查找并读取邮件 (双引擎支持: Gmail 原生语法 + IMAP RFC 3501 标准语法)"""
        clean_id = (message_id or "").strip()
        if not clean_id:
            return None

        folder = LABEL_SPECS[code].folder_name if code in LABEL_SPECS else code
        self.connection.select_folder(folder)
        client = self.connection.client

        # 1. 优先尝试 Gmail X-GM-EXT-1 专属扩展语法 (毫秒级全邮箱检索)
        uids: list[int] = []
        try:
            uids = client.gmail_search(f"rfc822msgid:{clean_id.strip('<>')}")
        except Exception:
            pass

        # 2. 回退至标准 IMAP RFC 3501 语法: HEADER Message-ID 检索 (通用各大邮件服务商)
        if not uids:
            try:
                uids = client.search([b"HEADER", b"Message-ID", clean_id.encode("utf-8")])
                if not uids and not clean_id.startswith("<"):
                    wrapped_id = f"<{clean_id}>"
                    uids = client.search([b"HEADER", b"Message-ID", wrapped_id.encode("utf-8")])
            except Exception:
                pass

        if not uids:
            return None

        return self.read_email_content(email_uid=uids[0], code=code, max_length=max_length)

    def search_emails(
        self,
        query: str = "",
        code: str = "inbox",
        unread_only: bool = False,
        sender: str = "",
        limit: int = 10,
    ) -> list[Email]:
        """按关键词、发件人、未读状态检索邮件，返回完整的 Email 领域实体列表 (Fail-Fast)"""
        folder = LABEL_SPECS[code].folder_name if code in LABEL_SPECS else code
        self.connection.select_folder(folder)
        client = self.connection.client

        uids: list[int] = []
        if query:
            try:
                uids = client.gmail_search(query)
            except Exception:
                pass

        if not uids:
            criteria = []
            if unread_only:
                criteria.append(b"UNSEEN")
            if sender:
                criteria.extend([b"FROM", sender.encode()])
            if query:
                criteria.extend([b"TEXT", query.encode()])
            uids = client.search(criteria if criteria else [b"ALL"])

        if not uids:
            return []

        selected_uids = list(reversed(uids))[:limit]
        emails: list[Email] = []
        for uid in selected_uids:
            fetch_data = client.fetch([uid], [b"RFC822", b"X-GM-LABELS"])
            if not fetch_data or uid not in fetch_data:
                continue
            raw_email_bytes = fetch_data[uid].get(b"RFC822", b"")
            if not raw_email_bytes:
                continue
            parsed = parse_email_message(raw_email_bytes)

            raw_labels = fetch_data[uid].get(b"X-GM-LABELS", ())
            labels: list[str] = [
                utf7_decode(lbl) if isinstance(lbl, bytes) else str(lbl)
                for lbl in raw_labels
            ]
            current_spec = LABEL_SPECS.get(code)
            if current_spec and current_spec.label_name not in labels:
                labels.insert(0, current_spec.label_name)

            codes = labels_to_codes(labels)
            if current_spec and current_spec.code not in codes:
                codes.insert(0, current_spec.code)

            emails.append(
                Email(
                    uid=uid,
                    message_id=parsed["message_id"],
                    subject=parsed["subject"],
                    from_addr=parsed["from_addr"],
                    to_addr=parsed["to_addr"],
                    date=parsed["date"],
                    snippet=parsed["body"][:1000],
                    body=parsed["body"],
                    raw_html=parsed["raw_html"],
                    attachments=parsed["attachments"],
                    unsubscribe_link=parsed["unsubscribe_link"],
                    labels=labels,
                    codes=codes,
                )
            )

        return emails
