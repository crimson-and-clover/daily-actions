"""
Gmail 标签体系与标签服务 (Labels)
包含统一名称的标签规格配置 (LABEL_SPECS) 与原生 X-GM-LABELS 变更原语 (LabelService)
"""

from collections.abc import Sequence

from imapclient.imap_utf7 import decode as utf7_decode

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


DESTINATION_CODES = ("inbox", "archive", "system_notification", "promotions", "verification_code", "finance_banking", "spam", "trash")


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
        顺序执行标签增删；调用方负责核验最终状态，不保证事务原子性。
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

    def route_emails(self, uids: Sequence[int], destination: str) -> None:
        """按 Gmail 全局 ID 重新定位并核验唯一去向；失败时不得提交已处理状态。"""
        if destination not in DESTINATION_CODES:
            raise ValueError(f"不支持的邮件去向：{destination}")
        if not uids:
            return
        source = self.connection.current_folder
        if not source:
            raise RuntimeError("邮件分流前必须选择来源目录")
        client = self.connection.client
        records = client.fetch(list(uids), [b"X-GM-MSGID"])
        if any(not records.get(uid, {}).get(b"X-GM-MSGID") for uid in uids):
            raise RuntimeError("来源邮件缺失或没有 Gmail 全局 ID，停止分流")
        identities = list(dict.fromkeys(records[uid][b"X-GM-MSGID"] for uid in uids))
        all_mail = next(
            (name for flags, _, name in client.list_folders() if b"\\All" in flags),
            None,
        )
        if not all_mail:
            raise RuntimeError("找不到 Gmail 所有邮件目录，停止分流")
        try:
            for gmail_id in identities:
                # Spam/Trash 不在所有邮件中；先 COPY 到目标目录建立可核验的成员关系。
                special_source = source in {LABEL_SPECS[c].folder_name for c in ("spam", "trash")}
                if special_source and source != LABEL_SPECS[destination].folder_name:
                    self.connection.select_folder(source)
                    source_uid = self._find_uid(gmail_id)
                    target_folder = LABEL_SPECS[destination].folder_name
                    client.copy([source_uid], target_folder)

                if destination in {"spam", "trash"}:
                    # 在来源外执行特殊去向添加；随后在目标目录处理剩余标签。
                    if not special_source:
                        self.connection.select_folder(all_mail)
                        uid = self._find_uid(gmail_id)
                        self.set_labels([uid], add=[destination])
                    folder = LABEL_SPECS[destination].folder_name
                else:
                    folder = all_mail
                self.connection.select_folder(folder)
                uid = self._find_uid(gmail_id)
                actual = self._destination_codes(uid, folder)
                self.set_labels(
                    [uid],
                    add=[] if destination in actual else [destination],
                    remove=sorted(actual - {destination}),
                )
                # 重新 SELECT 并按全局 ID 查找，避免依赖 STORE 返回值或失效的原 UID。
                self.connection.select_folder(folder)
                uid = self._find_uid(gmail_id)
                actual = self._destination_codes(uid, folder)
                if actual != {destination}:
                    raise RuntimeError(f"邮件 {gmail_id} 分流核验失败：期望 {destination}，实际 {sorted(actual)}")
        finally:
            # 后续批量操作仍使用来源目录的 UID，不能把所有邮件目录遗留给调用方。
            self.connection.select_folder(source)

    def _find_uid(self, gmail_id: int) -> int:
        matches = self.connection.client.search(["X-GM-MSGID", str(gmail_id)])
        if len(matches) != 1:
            raise RuntimeError(f"Gmail 邮件 {gmail_id} 在当前目录缺失或不唯一")
        return matches[0]

    def _destination_codes(self, uid: int, folder: str) -> set[str]:
        data = self.connection.client.fetch([uid], [b"X-GM-LABELS"])
        if uid not in data or b"X-GM-LABELS" not in data[uid]:
            raise RuntimeError("无法读取邮件最终标签")
        labels = [utf7_decode(v) if isinstance(v, bytes) else str(v) for v in data[uid][b"X-GM-LABELS"]]
        codes = set(labels_to_codes(labels)) & set(DESTINATION_CODES)
        # Gmail 的 X-GM-LABELS 会省略当前目录自身标签，必须补上实际成员关系。
        codes.update(code for code in DESTINATION_CODES if LABEL_SPECS[code].folder_name == folder)
        return codes

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
