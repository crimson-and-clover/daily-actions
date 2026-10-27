"""
Inbox Agent 工具系统 (Tools Definition & Modular Dispatcher)
基于单一标签原语 (apply_labels) 与正交日历、草稿、检索工具矩阵，全部工具由 Pydantic 自动导出
"""

import hashlib
from dataclasses import dataclass, field
from typing import Any

import openai
from pydantic import BaseModel, Field

from inbox_agent.imap import (
    LABEL_SPECS,
    DraftService,
    Email,
    FlagService,
    ImapConnection,
    LabelService,
    MessageRepo,
)
from inbox_agent.memory import InboxMemory
from utils.timezone import get_now_bjt, parse_bjt_datetime

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
    code: str | None = Field(default=None, description="UID 所属目录的标签代码，默认沿用当前运行模式目录")


class MarkFlagsArgs(BaseModel):
    """调整邮件的已读/未读状态或标星置顶旗标"""

    email_uids: list[int] = Field(description="邮件 UID 列表 (int)")
    is_read: bool | None = Field(default=None, description="是否标记已读 (True=已读, False=未读)")
    is_starred: bool | None = Field(default=None, description="是否标记星标 (True=标星, False=取消星标)")
    code: str | None = Field(default=None, description="邮件所在目录对应的标签代码，默认沿用当前运行模式目录")


class ReadEmailContentArgs(BaseModel):
    """读取单封邮件的完整正文和附件信息 (正文较长时将自动截断)"""

    email_uid: int = Field(description="邮件 UID (int)")
    code: str | None = Field(default=None, description="邮件所在目录对应的标签代码，默认沿用当前运行模式目录")
    max_length: int = Field(default=4000, description="读取最大字符长度，默认 4000")


class SearchEmailsArgs(BaseModel):
    """按关键词、发件人或未读状态检索邮件元数据"""

    query: str = Field(default="", description="搜索关键词或 Gmail 语法 (如 from:example.com)")
    code: str | None = Field(default=None, description="检索目标目录代码，默认沿用当前运行模式目录")
    unread_only: bool = Field(default=False, description="是否仅检索未读邮件")
    sender: str = Field(default="", description="限定发件人邮箱或名称")
    limit: int = Field(default=10, description="最大返回数量")


class CreateCalendarEventArgs(BaseModel):
    """从邮件中提炼具体日程、会议或还款截期 (DDL) 并持久化保存到待办日历池中"""

    title: str = Field(description="日程标题 (如：季度战略复盘会、信用卡还款日、酒店入住)")
    event_date: str = Field(description="具体日期 (格式严格为 YYYY-MM-DD)", pattern=r"^\d{4}-\d{2}-\d{2}$")
    message_id: str = Field(description="关联邮件的全局唯一 Message-ID (RFC 822)")
    event_time: str = Field(default="", description="具体时间点或区间 (如: '14:00' 或 '09:30-11:30')")
    timezone: str = Field(default="Asia/Shanghai", description="日程时区，默认 'Asia/Shanghai'")
    advance_days: int = Field(default=3, description="提前几天开始在简报中预警提醒 (默认 3 天)")
    action_items: list[str] = Field(default_factory=list, description="提取的具体行动项列表")
    priority: str = Field(default="P1", description="优先级 (P0=紧急重要, P1=重要待办, P2=常规提醒)")
    tldr: str = Field(default="", description="日程背景一句话说明")


class ListCalendarEventsArgs(BaseModel):
    """查询日历待办池中当前所有活跃的待办日程"""


class RemoveCalendarEventArgs(BaseModel):
    """从日历待办池中移除指定 ID 的日程事件 (如会议取消或改期重置)"""

    schedule_id: str = Field(description="要删除的日程唯一 ID (schedule_id)")


class CreateDraftArgs(BaseModel):
    """在 Gmail 草稿箱中创建一封邮件草稿 (支持新建或指定原邮件 ID 回复)"""

    to_addr: str = Field(description="收件人邮箱地址")
    subject: str = Field(description="草稿主题")
    body: str = Field(description="草稿正文内容")
    in_reply_to: str = Field(default="", description="关联回复的原邮件 Message-ID (可选)")


# ==============================================================================
# 2. 工具执行上下文 (Tool Context)
# ==============================================================================


@dataclass
class ToolContext:
    """贯穿 Agent 工具调用的全局执行上下文 (纯净无状态，由外部 Orchestrator 注入)"""

    connection: ImapConnection
    repo: MessageRepo
    label_service: LabelService
    flag_service: FlagService
    draft_service: DraftService
    memory: InboxMemory
    current_code: str = "inbox"
    current_emails: list[Email] = field(default_factory=list)


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
    invalid = [c for c in add + remove if c not in LABEL_SPECS]
    if invalid:
        return {
            "status": "error",
            "message": f"未定义的标签代码: {invalid}，合法代码为: {sorted(list(LABEL_SPECS.keys()))}",
        }

    # 切换至 UID 所属的目标目录上下文
    code = args.code or ctx.current_code
    folder = LABEL_SPECS[code].folder_name if code in LABEL_SPECS else code
    ctx.connection.select_folder(folder)

    # 底层执行原子标签操作
    ctx.label_service.set_labels(uids=uids, add=add, remove=remove)

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
    emails = ctx.repo.search_emails(
        query=args.query,
        code=code,
        unread_only=args.unread_only,
        sender=args.sender,
        limit=args.limit,
    )
    # 统一返回完整的 Email 对象字典 (包含全部 13 个字段)，不再丢失正文与附件
    results = [e.to_dict() for e in emails]
    return {"status": "success", "count": len(results), "results": results}


def _handle_create_calendar_event(args: CreateCalendarEventArgs, ctx: ToolContext) -> dict[str, Any]:
    title = args.title.strip()
    event_date = args.event_date.strip()
    m_id = (args.message_id or "").strip()

    if not title or not event_date:
        return {"status": "error", "message": "title 和 event_date 不能为空"}
    if not m_id:
        return {
            "status": "error",
            "message": "message_id 不能为空，日程必须绑定具体邮件的全局 Message-ID",
        }

    # 严格真实日历日期校验 (拦截 2026-02-30, 2026-13-01 等非法日期)
    try:
        raw_target = f"{event_date} {args.event_time.strip()}".strip()
        event_dt = parse_bjt_datetime(raw_target)
    except Exception:
        return {
            "status": "error",
            "message": f"event_date '{event_date}' 不是合法的日历日期 (格式须为 YYYY-MM-DD 且日期真实存在)",
        }

    # 强类型基准日校验：若事件日期早于今日（北京时间），防御性拦截加入日程池
    now_bjt = get_now_bjt()
    if event_dt.date() < now_bjt.date():
        return {
            "status": "ignored",
            "message": f"日程日期 {event_dt.format('YYYY-MM-DD')} 早于今日基准日 {now_bjt.format('YYYY-MM-DD')}，已过期失效，无需加入日程池",
        }

    email_info: dict[str, Any] = {}

    # 1. 优先从当前批次传入的邮件列表快速匹配
    for item in ctx.current_emails:
        if item.message_id == m_id:
            email_info = item.to_dict()
            break

    # 2. 本地历史已处理记录查验
    if not email_info and ctx.memory.is_processed(m_id):
        email_info = {"message_id": m_id}

    # 3. 若本地未命中且 IMAP 在线，调用双引擎检索真实性并补齐元数据
    if not email_info and ctx.connection.is_connected():
        try:
            fetched_email = ctx.repo.get_email_by_message_id(m_id, code=ctx.current_code)
            if fetched_email:
                email_info = fetched_email
        except Exception:
            pass

    # 4. 如果所有查验均判定不存在，直接拒绝防模型幻觉
    if not email_info and ctx.connection.is_connected():
        return {
            "status": "error",
            "message": f"Message-ID '{m_id}' 在当前上下文或邮箱中未检索到真实邮件，请确认 Message-ID 是否正确",
        }

    # 日程全局唯一 ID 仅跟随 Message-ID + 标题 + 日期派生
    seed = f"{m_id}|{title}|{event_dt.format('YYYY-MM-DD')}"
    derived_schedule_id = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]

    schedule_payload = {
        "schedule_id": derived_schedule_id,
        "message_id": m_id,
        "subject": email_info.get("subject", title),
        "from_addr": email_info.get("from_addr", ""),
        "title": title,
        "event_date": event_dt,
        "event_time": args.event_time.strip(),
        "timezone": args.timezone.strip() or "Asia/Shanghai",
        "advance_days": args.advance_days,
        "action_items": args.action_items,
        "priority": args.priority,
        "tldr": args.tldr or email_info.get("subject", title),
        "raw_body": email_info.get("body", ""),
    }

    item = ctx.memory.add_schedule(schedule_payload)
    # 即时落盘保存状态，防止进程中断导致日程丢失
    ctx.memory.save()
    item_dict = item.model_dump() if item is not None else schedule_payload

    return {
        "status": "success",
        "message": f"成功创建日程: {title} ({event_date})",
        "schedule": item_dict,
    }


def _handle_list_calendar_events(_args: ListCalendarEventsArgs, ctx: ToolContext) -> dict[str, Any]:
    events = ctx.memory.get_active_schedules()
    return {"status": "success", "count": len(events), "events": events}


def _handle_remove_calendar_event(args: RemoveCalendarEventArgs, ctx: ToolContext) -> dict[str, Any]:
    success = ctx.memory.remove_schedule(args.schedule_id)
    if success:
        ctx.memory.save()
    return {
        "status": "success" if success else "not_found",
        "schedule_id": args.schedule_id,
        "message": "日程已成功移除" if success else f"未找到 schedule_id 为 '{args.schedule_id}' 的日程",
    }


def _handle_create_email_draft(args: CreateDraftArgs, ctx: ToolContext) -> dict[str, Any]:
    ctx.draft_service.create_draft(
        to=args.to_addr,
        subject=args.subject,
        body=args.body,
        in_reply_to=args.in_reply_to,
    )
    draft_info = {
        "to_addr": args.to_addr,
        "subject": args.subject,
        "body": args.body,
        "in_reply_to": args.in_reply_to,
    }
    return {"status": "success", "draft": draft_info, "message": f"成功为 {args.to_addr} 创建草稿"}


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
        return {"status": "error", "message": f"未知的工具名称: '{fn_name}'"}
    model_cls, handler = TOOL_REGISTRY[fn_name]
    try:
        validated_args = args if isinstance(args, model_cls) else model_cls.model_validate(args)
    except Exception as e:
        return {"status": "error", "message": f"参数校验失败: {e}"}
    try:
        return handler(validated_args, context)
    except Exception as e:
        return {"status": "error", "message": f"执行工具 '{fn_name}' 异常: {e}"}
