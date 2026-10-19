"""
邮件状态标记服务 (FlagService)
负责邮件已读状态 (\\Seen) 与标星状态 (\\Flagged) 的原子设置 (UID 统一为原生 int，Fail-Fast)
"""

from collections.abc import Sequence

import imapclient

from inbox_agent.imap.connection import ImapConnection
from inbox_agent.imap.labels import LABEL_SPECS


class FlagService:
    """管理邮件的 IMAP 系统标志 (Flags)"""

    def __init__(self, connection: ImapConnection):
        self.connection = connection

    def mark_flags(
        self,
        email_uids: Sequence[int],
        is_read: bool | None = None,
        is_starred: bool | None = None,
        code: str = "inbox",
    ) -> None:
        """标记邮件已读/未读或标星状态 (Fail-Fast)"""
        if not email_uids:
            return

        folder = LABEL_SPECS[code].folder_name if code in LABEL_SPECS else code
        self.connection.select_folder(folder)
        client = self.connection.client

        if is_read is True:
            client.add_flags(email_uids, [imapclient.SEEN])
        elif is_read is False:
            client.remove_flags(email_uids, [imapclient.SEEN])

        if is_starred is True:
            client.add_flags(email_uids, [imapclient.FLAGGED])
        elif is_starred is False:
            client.remove_flags(email_uids, [imapclient.FLAGGED])
