"""
邮件草稿服务 (DraftService)
负责在 Gmail 草稿箱生成并追加 RFC 822 草稿邮件 (Fail-Fast)
"""

from collections.abc import Sequence
from email.message import EmailMessage

import imapclient

from inbox_agent.imap.connection import ImapConnection
from inbox_agent.imap.labels import LABEL_SPECS


class DraftService:
    """管理 Gmail 草稿邮件"""

    def __init__(self, connection: ImapConnection):
        self.connection = connection

    def create_draft(
        self,
        to: Sequence[str] | str,
        subject: str,
        body: str,
        in_reply_to: str = "",
    ) -> None:
        """在草稿箱中保存一封草稿邮件 (Fail-Fast)"""
        msg = EmailMessage()
        msg["From"] = self.connection.username
        msg["To"] = ", ".join(to) if isinstance(to, (list, tuple)) else str(to)
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        msg.set_content(body)

        draft_folder = LABEL_SPECS["drafts"].folder_name
        client = self.connection.client
        try:
            client.append(
                draft_folder,
                msg.as_bytes(),
                flags=[imapclient.DRAFT, imapclient.SEEN],
            )
        except Exception:
            # 兼容英文 Gmail 账号 "[Gmail]/Drafts"
            client.append(
                "[Gmail]/Drafts",
                msg.as_bytes(),
                flags=[imapclient.DRAFT, imapclient.SEEN],
            )
