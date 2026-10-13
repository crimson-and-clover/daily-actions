"""
Inbox Agent 工具系统 (Tools Definition & Modular Dispatcher)
基于单一标签原语 (apply_labels) 与正交日历、偏好工具矩阵，全部工具由 Pydantic 自动导出
"""

from dataclasses import dataclass, field
from typing import Any

import openai
from pydantic import BaseModel, Field

from inbox_agent.imap import (
    LABEL_SPECS,
    DraftService,
    FlagService,
    ImapConnection,
    LabelService,
    MessageRepo,
)
from inbox_agent.memory import InboxMemory

# ==============================================================================
# 1. Pydantic 工具入参模型 (用于自动导出标准 OpenAI Tool Docs)
# ==============================================================================


class ApplyLabelsArgs(BaseModel):
    """批量变更邮件标签（归档、分类、移入垃圾箱或解救）"""

    email_uids: list[int] = Field(description="邮件 UID 列表")
    add: list[str] = Field(
        default_factory=list,
        description="添加的标签: promotions(推广), system_notification(系统通知), verification_code(验证码), finance_banking(账单), archive(归档), spam(垃圾), trash(废弃), inbox(收件箱)",
    )
    remove: list[str] = Field(
        default_factory=list,
        description="移除的标签: inbox(移出收件箱), spam(解救垃圾) 等",
    )
    tldr: str = Field(default="", description="处置简要理由或备忘")


class MarkFlagsArgs(BaseModel):
    """调整邮件的已读/未读状态或标星置顶旗标"""

    email_uids: list[int] = Field(description="邮件 UID 列表 (int)")
    is_read: bool | None = Field(default=None, description="是否标记已读 (True=已读, False=未读)")
    is_starred: bool | None = Field(default=None, description="是否标记星标 (True=标星, False=取消星标)")
    code: str = Field(default="inbox", description="邮件所在目录对应的标签代码，默认 inbox")


class ReadEmailContentArgs(BaseModel):
    """读取单封邮件的完整正文和附件信息 (正文较长时将自动截断)"""

    email_uid: int = Field(description="邮件 UID (int)")
    code: str = Field(default="inbox", description="邮件所在目录对应的标签代码，默认 inbox")
    max_length: int = Field(default=4000, description="读取最大字符长度，默认 4000")


class SearchEmailsArgs(BaseModel):
    """按关键词、发件人或未读状态检索邮件元数据"""

    query: str = Field(default="", description="搜索关键词或 Gmail 语法 (如 from:example.com)")
    code: str = Field(default="inbox", description="检索目标目录代码，默认 inbox")
    unread_only: bool = Field(default=False, description="是否仅检索未读邮件")
    sender: str = Field(default="", description="限定发件人邮箱或名称")
    limit: int = Field(default=10, description="最大返回数量")


class CreateCalendarEventArgs(BaseModel):
    """从邮件中提炼具体日程、会议或还款截期 (DDL) 并持久化保存到待办日历池中"""

    email_uid: int = Field(description="关联的邮件 UID (int)")
    title: str = Field(description="日程标题 (如：季度战略复盘会、信用卡还款日)")
    event_date: str = Field(description="具体日期 (格式: YYYY-MM-DD)")
    event_time: str = Field(default="", description="具体时间点或区间 (如: '14:00' 或 '09:30-11:30')")
    advance_days: int = Field(default=3, description="提前几天开始在简报中预警提醒 (默认 3 天)")
    action_items: list[str] = Field(default_factory=list, description="提取的具体行动项列表")
    priority: str = Field(default="P1", description="优先级 (P0=紧急重要, P1=重要待办, P2=常规提醒)")
    tldr: str = Field(default="", description="日程背景一句话说明")


class ListCalendarEventsArgs(BaseModel):
    """查询日历待办池中当前所有活跃的待办日程"""


class RemoveCalendarEventArgs(BaseModel):
    """从日历待办池中移除匹配的日程事件 (如会议取消或改期重置)"""

    email_uid: int | None = Field(default=None, description="关联的邮件 UID (可选)")
    title: str = Field(default="", description="匹配的日程标题关键词 (可选)")
    event_date: str = Field(default="", description="匹配的日程日期 (可选)")


class CreateDraftArgs(BaseModel):
    """在 Gmail 草稿箱中创建一封邮件草稿 (支持新建或指定原邮件 ID 回复)"""

    to: str = Field(description="收件人邮箱地址")
    subject: str = Field(description="草稿主题")
    body: str = Field(description="草稿正文内容")
    in_reply_to: str = Field(default="", description="关联回复的原邮件 Message-ID (可选)")


# ==============================================================================
# 2. 批次跟踪与工具执行上下文 (Batch Tracker & Tool Context)
# ==============================================================================


@dataclass
class BatchTracker:
    """追踪批次/全局邮件处理决策与统计数据，用于生成报表"""

    # 邮件映射快速索引 {uid: dict}
    email_map: dict[int, dict] = field(default_factory=dict)
    # 单封邮件的综合三维决策状态 {uid: {"add": set[str], "remove": set[str], "triaged": bool, "tldr": str}}
    triage_decisions: dict[int, dict] = field(default_factory=dict)

    # 标签索引分组 {code: list[dict]}
    labeled_emails: dict[str, list[dict]] = field(default_factory=dict)

    # 日程池列表
    schedules: list[dict] = field(default_factory=list)
    # 草稿生成记录
    created_drafts: list[dict] = field(default_factory=list)
    # 垃圾箱解救记录
    rescued_items: list[dict] = field(default_factory=list)

    # 便捷属性访问，保证渲染器兼容：
    @property
    def importants(self) -> list[dict]:
        # 留存在收件箱中且标记重要或特定业务标签的邮件
        result = []
        for uid, dec in self.triage_decisions.items():
            if "inbox" not in dec.get("remove", set()):
                # 仍在收件箱
                email_item = self.email_map.get(uid)
                if email_item:
                    item_copy = dict(email_item)
                    item_copy["tldr"] = dec.get("tldr") or item_copy.get("subject", "")
                    result.append(item_copy)
        return result

    @property
    def systems(self) -> list[dict]:
        return self.labeled_emails.get("system_notification", [])

    @property
    def marketings(self) -> list[dict]:
        return self.labeled_emails.get("promotions", [])

    @property
    def spams(self) -> list[dict]:
        return self.labeled_emails.get("spam", [])

    @property
    def finance_bankings(self) -> list[dict]:
        return self.labeled_emails.get("finance_banking", [])

    @property
    def verification_codes(self) -> list[dict]:
        return self.labeled_emails.get("verification_code", [])

    @property
    def government_affairs(self) -> list[dict]:
        return self.labeled_emails.get("government_affairs", [])

    @property
    def marketings_moved_count(self) -> int:
        return sum(
            1
            for d in self.triage_decisions.values()
            if "promotions" in d.get("add", set()) and "inbox" in d.get("remove", set())
        )

    @property
    def systems_moved_count(self) -> int:
        return sum(
            1
            for d in self.triage_decisions.values()
            if "system_notification" in d.get("add", set()) and "inbox" in d.get("remove", set())
        )

    @property
    def spams_moved_count(self) -> int:
        return sum(
            1
            for d in self.triage_decisions.values()
            if "spam" in d.get("add", set()) and "inbox" in d.get("remove", set())
        )

    def register_batch_emails(self, emails: list[dict]):
        for e in emails:
            raw_uid = e.get("uid")
            if raw_uid is not None:
                uid = int(raw_uid)
                self.email_map[uid] = dict(e)
                if uid not in self.triage_decisions:
                    self.triage_decisions[uid] = {
                        "add": set(),
                        "remove": set(),
                        "triaged": False,
                        "tldr": "",
                    }

    def record_labels(
        self,
        uids: list[int],
        add: list[str],
        remove: list[str],
        tldr: str = "",
    ):
        for uid in uids:
            if uid not in self.triage_decisions:
                self.triage_decisions[uid] = {
                    "add": set(),
                    "remove": set(),
                    "triaged": True,
                    "tldr": tldr,
                }
            dec = self.triage_decisions[uid]
            dec["triaged"] = True
            dec["add"].update(add)
            dec["remove"].update(remove)
            if tldr:
                dec["tldr"] = tldr

            email_item = self.email_map.get(uid, {"uid": uid})
            item_copy = dict(email_item)
            item_copy["tldr"] = dec["tldr"] or item_copy.get("subject", "")

            # 如果是从垃圾箱解救 (remove spam, add inbox)
            if "spam" in remove and ("inbox" in add or not add):
                if not any(it.get("uid") == uid for it in self.rescued_items):
                    self.rescued_items.append(item_copy)

            # 更新各分组索引
            for code in add:
                group = self.labeled_emails.setdefault(code, [])
                if not any(it.get("uid") == uid for it in group):
                    group.append(item_copy)


@dataclass
class ToolContext:
    """贯穿 Agent 工具调用的全局执行上下文"""

    connection: ImapConnection
    repo: MessageRepo
    label_service: LabelService
    flag_service: FlagService
    draft_service: DraftService
    memory: InboxMemory
    tracker: BatchTracker
    current_code: str = "inbox"


# ==============================================================================
# 3. 模块化工具处理器实现 (Modular Tool Handlers)
# ==============================================================================


def _handle_apply_labels(args: ApplyLabelsArgs, ctx: ToolContext) -> dict[str, Any]:
    uids = args.email_uids
    add = [a.strip() for a in args.add if a.strip()]
    remove = [r.strip() for r in args.remove if r.strip()]
    tldr = args.tldr

    if not uids:
        return {"status": "error", "message": "email_uids 不能为空"}

    # 校验标签代码是否合法
    for code in add + remove:
        if code not in LABEL_SPECS:
            raise ValueError(f"未定义的标签代码: '{code}'，合法代码为: {sorted(list(LABEL_SPECS.keys()))}")

    # 底层执行原子标签操作
    ctx.label_service.set_labels(uids=uids, add=add, remove=remove)

    # 记录到批次追踪器
    ctx.tracker.record_labels(uids=uids, add=add, remove=remove, tldr=tldr)

    add_names = [LABEL_SPECS[a].label_name for a in add]
    remove_names = [LABEL_SPECS[r].label_name for r in remove]
    return {
        "status": "success",
        "affected_uids": uids,
        "added_labels": add_names,
        "removed_labels": remove_names,
        "tldr": tldr,
        "message": f"成功为 {len(uids)} 封邮件变更标签: +{add_names} -{remove_names}",
    }


def _handle_mark_flags(args: MarkFlagsArgs, ctx: ToolContext) -> dict[str, Any]:
    uids = args.email_uids
    if not uids:
        return {"status": "error", "message": "email_uids 不能为空"}

    code = args.code or ctx.current_code
    ctx.flag_service.mark_flags(email_uids=uids, is_read=args.is_read, is_starred=args.is_starred, code=code)
    return {
        "status": "success",
        "affected_uids": uids,
        "is_read": args.is_read,
        "is_starred": args.is_starred,
        "code": code,
        "message": f"已成功更新 {len(uids)} 封邮件的标志状态",
    }


def _handle_read_email_content(args: ReadEmailContentArgs, ctx: ToolContext) -> dict[str, Any]:
    code = args.code or ctx.current_code
    return ctx.repo.read_email_content(email_uid=args.email_uid, code=code, max_length=args.max_length)


def _handle_search_emails(args: SearchEmailsArgs, ctx: ToolContext) -> dict[str, Any]:
    code = args.code or ctx.current_code
    results = ctx.repo.search_emails(
        query=args.query,
        code=code,
        unread_only=args.unread_only,
        sender=args.sender,
        limit=args.limit,
    )
    return {"status": "success", "count": len(results), "results": results}


def _handle_create_calendar_event(args: CreateCalendarEventArgs, ctx: ToolContext) -> dict[str, Any]:
    title = args.title.strip()
    event_date = args.event_date.strip()
    if not title or not event_date:
        return {"status": "error", "message": "title 和 event_date 不能为空"}

    email_info = ctx.tracker.email_map.get(args.email_uid, {})
    schedule_item = {
        "email_uid": args.email_uid,
        "message_id": email_info.get("message_id", ""),
        "subject": email_info.get("subject", title),
        "from": email_info.get("from", ""),
        "title": title,
        "event_date": event_date,
        "event_time": args.event_time.strip(),
        "advance_days": args.advance_days,
        "action_items": args.action_items,
        "priority": args.priority,
        "tldr": args.tldr or email_info.get("subject", title),
        "raw_body": email_info.get("body", ""),
    }

    ctx.memory.add_schedule(schedule_item)
    ctx.tracker.schedules.append(schedule_item)

    return {
        "status": "success",
        "message": f"成功创建日程: {title} ({event_date})",
        "schedule": schedule_item,
    }


def _handle_list_calendar_events(_args: ListCalendarEventsArgs, ctx: ToolContext) -> dict[str, Any]:
    events = ctx.memory.get_active_schedules()
    return {"status": "success", "count": len(events), "events": events}


def _handle_remove_calendar_event(args: RemoveCalendarEventArgs, ctx: ToolContext) -> dict[str, Any]:
    msg_id = None
    if args.email_uid is not None and args.email_uid in ctx.tracker.email_map:
        msg_id = ctx.tracker.email_map[args.email_uid].get("message_id")

    removed = ctx.memory.remove_schedule(message_id=msg_id, subject=args.title, event_date=args.event_date)
    return {"status": "success", "removed_count": len(removed), "removed_events": removed}


def _handle_create_email_draft(args: CreateDraftArgs, ctx: ToolContext) -> dict[str, Any]:
    draft_info = ctx.draft_service.create_draft(
        to=args.to,
        subject=args.subject,
        body=args.body,
        in_reply_to=args.in_reply_to,
    )
    ctx.tracker.created_drafts.append(draft_info)
    return {"status": "success", "draft": draft_info, "message": f"成功为 {args.to} 创建草稿"}


# ==============================================================================
# 4. 工具注册表与分发器 (Tool Registry, AGENT_TOOLS & Dispatcher)
# ==============================================================================

TOOL_REGISTRY: dict[str, tuple[type[BaseModel], Any]] = {
    "apply_labels": (ApplyLabelsArgs, _handle_apply_labels),
    "mark_email_flags": (MarkFlagsArgs, _handle_mark_flags),
    "read_email_content": (ReadEmailContentArgs, _handle_read_email_content),
    "search_emails": (SearchEmailsArgs, _handle_search_emails),
    "create_calendar_event": (CreateCalendarEventArgs, _handle_create_calendar_event),
    "list_calendar_events": (ListCalendarEventsArgs, _handle_list_calendar_events),
    "remove_calendar_event": (RemoveCalendarEventArgs, _handle_remove_calendar_event),
    "create_email_draft": (CreateDraftArgs, _handle_create_email_draft),
}

TOOL_HANDLERS = {name: handler for name, (_, handler) in TOOL_REGISTRY.items()}

AGENT_TOOLS: list[dict[str, Any]] = [
    openai.pydantic_function_tool(model_cls, name=name)
    for name, (model_cls, _) in TOOL_REGISTRY.items()
]


def execute_tool(fn_name: str, args: dict[str, Any] | BaseModel, context: ToolContext) -> dict[str, Any]:
    """统一分发并执行大模型发起的工具调用，入参经 Pydantic 模型严格校验后传入对应 Handler"""
    if fn_name not in TOOL_REGISTRY:
        raise ValueError(f"未知的工具名称: '{fn_name}'")
    model_cls, handler = TOOL_REGISTRY[fn_name]
    try:
        validated_args = args if isinstance(args, model_cls) else model_cls.model_validate(args)
    except Exception as e:
        return {"status": "error", "message": f"参数校验失败: {e}"}
    return handler(validated_args, context)
