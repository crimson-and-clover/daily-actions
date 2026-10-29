"""
Inbox Agent 决策与报表数据追踪器 (BatchTracker)
负责在多批次 ReAct 会话中捕获工具调用的处置决策、日程提炼与移动统计，为简报渲染与运维汇总提供数据支撑
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from inbox_agent.imap.models import Email
from inbox_agent.rules import is_internal_ci


@dataclass
class EmailDecision:
    """
    单封邮件在 ReAct 决策过程中的处置记录。

    Attributes:
        add: 累积添加的标签集合（如 "promotions", "system_notification", "spam"）
        remove: 累积移除的标签集合（如 "inbox", "spam"）
        triaged: 是否已被模型显式处置（通过 apply_labels 确立去向）
        tldr: 模型的处置备忘、分类理由或内容提炼
    """

    add: set[str] = field(default_factory=set)
    remove: set[str] = field(default_factory=set)
    triaged: bool = False
    tldr: str = ""


class BatchTracker:
    """
    追踪批次/全局邮件处理决策与统计数据，供邮件日报渲染与审计使用。

    设计定位：
    - 作为纯净的收集器与报表投影器（Projection），解耦底层的 IMAP 工具执行层与上层的日报渲染层；
    - 在多批次独立上下文的 ReAct 执行中保持累积状态，记录所有邮件的标签变动、日程沉淀与垃圾箱解救情况。
    """

    def __init__(self):
        # 邮件映射快速索引：按原生 UID 缓存 Email 实体，便于快速提取主题、发件人等元数据
        self.email_map: dict[int, Email] = {}
        # 决策映射：记录每个 UID 的最终标签增删与处置理由
        self.triage_decisions: dict[int, EmailDecision] = {}
        # 日程池列表：收集大模型通过 create_calendar_event 成功提取的新增日程
        self.schedules: list[dict[str, Any]] = []
        # 草稿生成记录：收集大模型通过 create_email_draft 拟定的回复草稿
        self.created_drafts: list[dict[str, Any]] = []
        # 垃圾箱解救记录：收集从 [Gmail]/Spam 中被成功识别为误杀并放回收件箱的邮件
        self.rescued_items: list[dict[str, Any]] = []

    def register_batch_emails(self, emails: Sequence[Email]) -> None:
        """
        在每批次处理开始前，注册当前批次的所有 Email 实体。
        建立 UID -> Email 快速索引，并为尚未追踪的邮件初始化空决策状态。
        """
        for e in emails:
            if e.uid is not None:
                self.email_map[e.uid] = e
                if e.uid not in self.triage_decisions:
                    self.triage_decisions[e.uid] = EmailDecision()

    def record_labels(
        self,
        uids: list[int],
        add: list[str],
        remove: list[str],
        tldr: str = "",
        current_code: str = "inbox",
    ) -> None:
        """
        记录工具 `apply_labels` 成功执行后的标签变更与处置理由。

        Args:
            uids: 受到本次标签操作影响的邮件 UID 列表
            add: 本次操作添加的业务标签代码列表
            remove: 本次操作移除的业务标签代码列表
            tldr: 模型的处置说明或备忘
            current_code: 当前处理所在的目录代码（"inbox" 或 "spam"）
        """
        for uid in uids:
            if uid not in self.triage_decisions:
                self.triage_decisions[uid] = EmailDecision(triaged=True, tldr=tldr)
            dec = self.triage_decisions[uid]
            dec.triaged = True
            dec.add.update(add)
            dec.remove.update(remove)
            if tldr:
                dec.tldr = tldr

            # 【垃圾箱解救识别逻辑】
            # 当且仅当当前目录为 spam 垃圾箱，且操作中移除了 "spam" 标签，
            # 同时目标去向包含收件箱（或保持默认收件箱）时，确认为有效解救的正常邮件
            if current_code == "spam" and "spam" in remove and ("inbox" in add or not add):
                email_obj = self.email_map.get(uid)
                item_dict = self._email_to_report_dict(email_obj, uid=uid, tldr=dec.tldr)
                if not any(r.get("uid") == uid for r in self.rescued_items):
                    self.rescued_items.append(item_dict)

    def record_schedule(self, schedule_dict: dict[str, Any]) -> None:
        """记录成功通过工具创建的日程事项"""
        self.schedules.append(schedule_dict)

    def record_draft(self, draft_dict: dict[str, Any]) -> None:
        """记录成功通过工具拟定的回复草稿"""
        self.created_drafts.append(draft_dict)

    def _email_to_report_dict(self, e: Email | None, uid: int, tldr: str = "") -> dict[str, Any]:
        """
        将 Email 领域模型实体转换为模板渲染友好的扁平字典。

        设计考虑：
        - 补充 'from' 键（对应 e.from_addr），以兼容 Jinja2 模板中的 `item.from` 字段访问语法；
        - 提供 fallback 默认值，防范极端情况下无法检索到原始实体的情形；
        - 统一注入有效 tldr 作为事项要点或垃圾判定原因。
        """
        if e is None:
            return {
                "uid": uid,
                "subject": "无主题",
                "from": "未知发件人",
                "from_addr": "未知发件人",
                "tldr": tldr,
                "reason": tldr,
            }
        effective_tldr = tldr or e.subject or ""
        return {
            "uid": e.uid,
            "message_id": e.message_id,
            "subject": e.subject or "无主题",
            "from": e.from_addr or "未知发件人",
            "from_addr": e.from_addr or "未知发件人",
            "to": e.to_addr,
            "date": e.date,
            "snippet": e.snippet,
            "body": e.body,
            "attachments": e.attachments,
            "unsubscribe_link": e.unsubscribe_link,
            "tldr": effective_tldr,
            "reason": effective_tldr,
        }

    # =========================================================================
    # 报表投影属性 (用于直接传递给 render_email_report 渲染 HTML)
    # =========================================================================

    @property
    def importants(self) -> list[dict[str, Any]]:
        """
        留存在收件箱中的高优先级/重要来信。
        判定准则：模型在处置时未将其移出收件箱（remove 中不包含 'inbox'）。
        """
        result = []
        for uid, dec in self.triage_decisions.items():
            if "inbox" not in dec.remove:
                e = self.email_map.get(uid)
                result.append(self._email_to_report_dict(e, uid=uid, tldr=dec.tldr))
        return result

    @property
    def systems(self) -> list[dict[str, Any]]:
        """被归档至「系统通知」专属目录的邮件列表（add 中包含 'system_notification'，已过滤内部 CI 报告）"""
        result = []
        for uid, dec in self.triage_decisions.items():
            if "system_notification" in dec.add:
                e = self.email_map.get(uid)
                # 过滤自建 CI 任务报告，不在日报展示层冗余呈现
                if e and is_internal_ci(e.subject):
                    continue
                result.append(self._email_to_report_dict(e, uid=uid, tldr=dec.tldr))
        return result

    @property
    def marketings(self) -> list[dict[str, Any]]:
        """被归档至「商业推广」专属目录的邮件列表（add 中包含 'promotions'）"""
        result = []
        for uid, dec in self.triage_decisions.items():
            if "promotions" in dec.add:
                e = self.email_map.get(uid)
                result.append(self._email_to_report_dict(e, uid=uid, tldr=dec.tldr))
        return result

    @property
    def spams(self) -> list[dict[str, Any]]:
        """被移入垃圾箱的恶意欺诈/钓鱼邮件列表（add 中包含 'spam'）"""
        result = []
        for uid, dec in self.triage_decisions.items():
            if "spam" in dec.add:
                e = self.email_map.get(uid)
                result.append(self._email_to_report_dict(e, uid=uid, tldr=dec.tldr))
        return result

    @property
    def marketings_moved_count(self) -> int:
        """从收件箱成功移入商业推广目录的邮件总数（add 包含 promotions 且 remove 包含 inbox）"""
        return sum(1 for d in self.triage_decisions.values() if "promotions" in d.add and "inbox" in d.remove)

    @property
    def systems_moved_count(self) -> int:
        """从收件箱成功移入系统通知目录的邮件总数（排除内部自发 CI 简报，与 systems 列表展示口径严格一致）"""
        count = 0
        for uid, d in self.triage_decisions.items():
            if "system_notification" in d.add and "inbox" in d.remove:
                e = self.email_map.get(uid)
                if e and is_internal_ci(e.subject):
                    continue
                count += 1
        return count

    @property
    def spams_moved_count(self) -> int:
        """从收件箱成功移入垃圾邮件目录的邮件总数（add 包含 spam 且 remove 包含 inbox）"""
        return sum(1 for d in self.triage_decisions.values() if "spam" in d.add and "inbox" in d.remove)
