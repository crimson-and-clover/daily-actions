"""
Gmail 标签体系与标签服务 (Labels)
包含统一名称的标签规格配置 (LABEL_SPECS) 与原生 X-GM-LABELS 变更原语 (LabelService)
"""

from collections.abc import Sequence

from inbox_agent.imap.connection import ImapConnection
from inbox_agent.imap.models import LabelSpec

# 全局不可变标签注册表 (直接使用标签名，由 imapclient 自动负责传输层编码)
LABEL_SPECS: dict[str, LabelSpec] = {
    "inbox": LabelSpec(code="inbox", label_name="\\Inbox", folder_name="INBOX"),
    "spam": LabelSpec(code="spam", label_name="\\Spam", folder_name="[Gmail]/垃圾邮件"),
    "trash": LabelSpec(code="trash", label_name="\\Trash", folder_name="[Gmail]/已删除邮件"),
    "drafts": LabelSpec(code="drafts", label_name="\\Drafts", folder_name="[Gmail]/草稿"),
    "archive": LabelSpec(code="archive", label_name="归档", folder_name="归档"),
    "promotions": LabelSpec(code="promotions", label_name="商业推广", folder_name="商业推广"),
    "system_notification": LabelSpec(code="system_notification", label_name="系统通知", folder_name="系统通知"),
    "verification_code": LabelSpec(code="verification_code", label_name="验证码", folder_name="验证码"),
    "finance_banking": LabelSpec(code="finance_banking", label_name="对账单", folder_name="对账单"),
}

# 构建从 Gmail 原生标签名与文件夹名到系统业务代码的反向映射表
LABEL_TO_CODE_MAP: dict[str, str] = {}
for code, spec in LABEL_SPECS.items():
    LABEL_TO_CODE_MAP[spec.label_name.lower()] = code
    LABEL_TO_CODE_MAP[spec.folder_name.lower()] = code
    LABEL_TO_CODE_MAP[code.lower()] = code


def labels_to_codes(labels: Sequence[str]) -> list[str]:
    """将 Gmail 原生标签列表解析并映射为业务规范代码列表 (codes)"""
    codes: list[str] = []
    for lbl in labels:
        c = LABEL_TO_CODE_MAP.get(lbl.strip().lower())
        if c and c not in codes:
            codes.append(c)
    return codes


class LabelService:
    """管理邮件的 Gmail 标签增删与分类 (基于 X-GM-LABELS，UID 统一为 int，Fail-Fast)"""

    def __init__(self, connection: ImapConnection):
        self.connection = connection

    def set_labels(
        self,
        uids: Sequence[int],
        add: Sequence[str] = (),
        remove: Sequence[str] = (),
    ) -> None:
        """
        原子标签变更原语：同时支持批量增删标签
        例如：归档商业推广：add=["promotions"], remove=["inbox"]
        """
        if not uids or (not add and not remove):
            return

        client = self.connection.client

        if add:
            target_add = [LABEL_SPECS[a].label_name if a in LABEL_SPECS else a for a in add]
            client.add_gmail_labels(uids, target_add)

        if remove:
            target_remove = [LABEL_SPECS[r].label_name if r in LABEL_SPECS else r for r in remove]
            client.remove_gmail_labels(uids, target_remove)

    def ensure_folder(self, folder_name: str) -> str:
        """确保指定文件夹存在，如不存在则创建"""
        client = self.connection.client
        if not client.folder_exists(folder_name):
            try:
                client.create_folder(folder_name)
            except Exception:
                # 若已存在或并发创建则忽略
                pass
        return folder_name
