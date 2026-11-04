"""
Inbox Agent 决策与报表数据追踪器 (BatchTracker)
负责在多批次 ReAct 会话中捕获工具调用的处置决策、日程提炼与移动统计，为简报渲染与运维汇总提供数据支撑
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from inbox_agent.config import GMAIL_USER
from inbox_agent.imap.labels import DESTINATION_CODES
from inbox_agent.imap.models import Email
from inbox_agent.rules import is_internal_ci


@dataclass
class EmailDecision:
    """
    单封邮件在 ReAct 决策过程中的处置记录。

    Attributes:
        destination: 最后一次成功处置的唯一最终去向
        source_code: 邮件首次成功处置时的来源目录
        tldr: 模型的处置备忘、分类理由或内容提炼
        is_internal_ci: 是否属于系统自动化任务或 CI 简报（硬规则过滤标记）
    """

    destination: str | None = None
    source_code: str | None = None
    tldr: str = ""
    is_internal_ci: bool = False


class BatchTracker:
    """
    追踪批次/全局邮件处理决策与统计数据，供邮件日报渲染与审计使用。

    设计定位：
    - 作为纯净的收集器与报表投影器（Projection），解耦底层的 IMAP 工具执行层与上层的日报渲染层；
    - 在多批次独立上下文的 ReAct 执行中保持累积状态，记录所有邮件的标签变动、日程沉淀与垃圾箱解救情况。
    """

    def __init__(self, user_email: str = ""):
        self.user_email = user_email or GMAIL_USER
        # 邮件映射快速索引：按 Message-ID 缓存 Email 实体，便于快速提取主题、发件人等元数据
        self.email_map: dict[str, Email] = {}
        # 决策映射：记录每个 Message-ID 的来源、唯一最终去向与处置理由
        self.triage_decisions: dict[str, EmailDecision] = {}
        # 日程池列表：收集大模型通过 create_calendar_event 成功提取的新增日程
        self.schedules: list[dict[str, Any]] = []
        # 草稿生成记录：收集大模型通过 create_email_draft 拟定的回复草稿
        self.created_drafts: list[dict[str, Any]] = []

    def register_batch_emails(self, emails: Sequence[Email]) -> None:
        """
        在每批次处理开始前，注册当前批次的所有 Email 实体。
        建立 Message-ID -> Email 快速索引，并为尚未追踪的邮件初始化空决策状态。
        """
        for e in emails:
            if e.message_id:
                self.email_map[e.message_id] = e
                self.triage_decisions.setdefault(e.message_id, EmailDecision())

    def record_route(
        self,
        message_ids: list[str],
        destination: str,
        tldr: str = "",
        source_code: str = "inbox",
        is_internal_ci: bool = False,
    ) -> None:
        """按已注册邮件的 Message-ID 记录成功处置，避免目录间 UID 碰撞。"""
        if destination not in DESTINATION_CODES:
            raise ValueError("每次成功处置必须明确一个最终去向")
        if any(message_id not in self.email_map for message_id in message_ids):
            raise ValueError("处置记录必须绑定已注册的邮件 Message-ID")
        for message_id in message_ids:
            dec = self.triage_decisions[message_id]
            if dec.source_code is None:
                dec.source_code = source_code
            dec.destination = destination
            if is_internal_ci:
                dec.is_internal_ci = True
            if tldr:
                dec.tldr = tldr

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
    def rescued_items(self) -> list[dict[str, Any]]:
        """按最终去向投影垃圾箱解救项，后续改判会自动反映在结果中。"""
        return [
            self._email_to_report_dict(self.email_map.get(message_id), uid=self.email_map[message_id].uid, tldr=dec.tldr)
            for message_id, dec in self.triage_decisions.items()
            if dec.source_code == "spam" and dec.destination == "inbox"
        ]

    @property
    def importants(self) -> list[dict[str, Any]]:
        """
        留存在收件箱中的高优先级/重要来信。
        判定准则：最终 destination 为 inbox；未处置邮件不算已确认留存。
        """
        result = []
        for message_id, dec in self.triage_decisions.items():
            if dec.destination == "inbox":
                e = self.email_map.get(message_id)
                result.append(self._email_to_report_dict(e, uid=self.email_map[message_id].uid, tldr=dec.tldr))
        return result

    def _is_ci_email(self, message_id: str, dec: EmailDecision) -> bool:
        """
        判定某封邮件是否属于内部自动化 CI 任务简报（需排除在简报展示与通知统计之外）。

        判定原则：
        1. 优先读取硬规则预过滤阶段标记的 dec.is_internal_ci；
        2. 若未显式标记，执行带发件人防伪造的安全校验，严防外部仿冒前缀导致邮件被恶意隐身。
        """
        if dec.is_internal_ci:
            return True
        e = self.email_map.get(message_id)
        if not e:
            return False
        return is_internal_ci(
            subject=e.subject or "",
            sender=e.from_addr or "",
            my_email=self.user_email,
        )

    @property
    def systems(self) -> list[dict[str, Any]]:
        """最终去向为系统通知的邮件，过滤内部 CI 报告。"""
        result = []
        for message_id, dec in self.triage_decisions.items():
            if dec.destination == "system_notification":
                # 过滤自建 CI 任务报告，不在日报展示层冗余呈现（严格对齐发件人校验，防止外部仿冒前缀隐身）
                if self._is_ci_email(message_id, dec):
                    continue
                e = self.email_map.get(message_id)
                result.append(self._email_to_report_dict(e, uid=self.email_map[message_id].uid, tldr=dec.tldr))
        return result

    @property
    def marketings(self) -> list[dict[str, Any]]:
        """最终去向为商业推广的邮件。"""
        result = []
        for message_id, dec in self.triage_decisions.items():
            if dec.destination == "promotions":
                e = self.email_map.get(message_id)
                result.append(self._email_to_report_dict(e, uid=self.email_map[message_id].uid, tldr=dec.tldr))
        return result

    @property
    def spams(self) -> list[dict[str, Any]]:
        """最终去向为 Spam 的邮件。"""
        result = []
        for message_id, dec in self.triage_decisions.items():
            if dec.destination == "spam":
                e = self.email_map.get(message_id)
                result.append(self._email_to_report_dict(e, uid=self.email_map[message_id].uid, tldr=dec.tldr))
        return result

    @property
    def marketings_moved_count(self) -> int:
        """来源为 Inbox 且最终去向为商业推广的邮件总数。"""
        return sum(1 for d in self.triage_decisions.values() if d.source_code == "inbox" and d.destination == "promotions")

    @property
    def systems_moved_count(self) -> int:
        """从收件箱成功移入系统通知目录的邮件总数（排除内部自发 CI 简报，与 systems 列表展示口径严格一致）"""
        count = 0
        for message_id, d in self.triage_decisions.items():
            if d.source_code == "inbox" and d.destination == "system_notification":
                if self._is_ci_email(message_id, d):
                    continue
                count += 1
        return count

    @property
    def spams_moved_count(self) -> int:
        """来源为 Inbox 且最终去向为 Spam 的邮件总数。"""
        return sum(1 for d in self.triage_decisions.values() if d.source_code == "inbox" and d.destination == "spam")
