"""
Inbox Agent 工具系统 (Tools Definition & Modular Dispatcher)
定义大模型可调用的标准 Function Calling 接口，并采用独立 Handler 模块化执行
"""

from dataclasses import dataclass, field
from typing import Any

from inbox_agent.imap_client import GmailClient, mutf7_decode
from inbox_agent.memory import InboxMemory


@dataclass
class BatchTracker:
    """追踪单批次/全局邮件处理动作与数据，用于生成分类报表"""

    # 各类别列表 (用于渲染 HTML 报告)
    schedules: list[dict] = field(default_factory=list)
    importants: list[dict] = field(default_factory=list)
    systems: list[dict] = field(default_factory=list)
    marketings: list[dict] = field(default_factory=list)
    spams: list[dict] = field(default_factory=list)
    verification_codes: list[dict] = field(default_factory=list)  # 验证码与短期口令
    finance_bankings: list[dict] = field(default_factory=list)  # 银行与证券对账单/通知
    government_affairs: list[dict] = field(default_factory=list)  # 政府事务与政务公函

    # 移动计数
    marketings_moved_count: int = 0
    systems_moved_count: int = 0
    spams_moved_count: int = 0

    # 邮件映射快速索引 {uid: dict}
    email_map: dict[str, dict] = field(default_factory=dict)
    # UID 处置标记 {uid: category}
    triage_status: dict[str, str] = field(default_factory=dict)
    # 草稿生成记录
    created_drafts: list[dict] = field(default_factory=list)
    # 垃圾箱解救记录
    rescued_items: list[dict] = field(default_factory=list)

    def register_batch_emails(self, emails: list[dict]):
        for e in emails:
            uid = str(e.get("uid", ""))
            if uid:
                self.email_map[uid] = dict(e)

    def mark_triaged(
        self,
        uid: str,
        category: str,
        tldr: str = "",
        priority: str = "P1",
        event_date: str = "",
        event_time: str = "",
        action_items: list[str] | None = None,
    ):
        base_item = dict(self.email_map.get(uid, {"uid": uid}))
        base_item.update({
            "category": category,
            "tldr": tldr or base_item.get("subject", ""),
            "priority": priority,
            "event_date": event_date,
            "event_time": event_time,
            "action_items": action_items or [],
        })
        self.triage_status[uid] = category

        category_lists = {
            "schedule": self.schedules,
            "important": self.importants,
            "newsletter_system": self.systems,
            "marketing": self.marketings,
            "spam": self.spams,
            "verification_code": self.verification_codes,
            "finance_banking": self.finance_bankings,
            "government_affairs": self.government_affairs,
        }

        target_list = category_lists.get(category)
        if target_list is not None and not any(item.get("uid") == uid for item in target_list):
            target_list.append(base_item)


@dataclass
class ToolContext:
    """Agent 工具执行上下文容器"""

    client: GmailClient
    memory: InboxMemory
    tracker: BatchTracker
    current_batch_emails: list[dict] = field(default_factory=list)


# OpenAI Function Calling 规范的工具描述清单
AGENT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "move_emails",
            "description": "批量将邮件移动到指定的归档分类文件夹（如商业推广、系统通知、Spam 垃圾邮件、Trash 回收站等）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_uids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要移动的邮件 UID 列表，例如 ['101', '102']",
                    },
                    "target_folder": {
                        "type": "string",
                        "description": "目标文件夹名称，支持: '商业推广', '系统通知', 'Spam' (垃圾邮件), 'Trash' (回收站), 或指定确切名称",
                    },
                    "category": {
                        "type": "string",
                        "enum": [
                            "marketing",
                            "newsletter_system",
                            "verification_code",
                            "finance_banking",
                            "government_affairs",
                            "spam",
                            "archive",
                        ],
                        "description": "归档分类类别：marketing (商业推广营销), newsletter_system (系统通知资讯), verification_code (验证码), finance_banking (银行证券对账单), government_affairs (政府事务), spam (恶意欺诈垃圾), archive (常规归档)",
                    },
                    "tldr": {
                        "type": "string",
                        "description": "对所移动邮件的简要特征/原因概括说明",
                    },
                },
                "required": ["email_uids", "target_folder"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_email_content",
            "description": "按 UID 读取单封邮件的完整正文、发件人/收件人详情以及附件信息。仅在 snippet 摘要不足以确认细节、或需要深度提取会议议程/复杂账单/重要内容时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_uid": {
                        "type": "string",
                        "description": "邮件 UID",
                    },
                    "max_length": {
                        "type": "integer",
                        "description": "正文最大截断长度，默认 4000 字符",
                    },
                },
                "required": ["email_uid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_email_flags",
            "description": "标记邮件状态，支持标记已读/未读、或添加星标置顶（Starred/Flagged）。对于重要来信、政务公函、银行账单等留在 INBOX 的邮件进行状态维护与加星标。",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_uids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "邮件 UID 列表",
                    },
                    "is_read": {
                        "type": "boolean",
                        "description": "是否标记为已读 (True=已读, False=未读)",
                    },
                    "is_starred": {
                        "type": "boolean",
                        "description": "是否标记星标/高优旗标 (True=加星标)",
                    },
                    "category": {
                        "type": "string",
                        "enum": [
                            "important",
                            "finance_banking",
                            "government_affairs",
                            "verification_code",
                            "schedule",
                        ],
                        "description": "邮件归属类别：important (重要工作来信), finance_banking (银行与证券通知/对账单), government_affairs (政府政务公函), verification_code (验证码口令), schedule (日程待办)",
                    },
                    "tldr": {
                        "type": "string",
                        "description": "简要说明重点所在",
                    },
                },
                "required": ["email_uids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": "从邮件中提取日程、会议或重要到期日 (DDL)，在日程池中创建提醒并持久化。此邮件将安全保留在 INBOX 中。",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_uid": {
                        "type": "string",
                        "description": "关联的邮件 UID",
                    },
                    "title": {
                        "type": "string",
                        "description": "日程标题 (如：季度战略复盘会、信用卡还款日)",
                    },
                    "event_date": {
                        "type": "string",
                        "description": "具体日期 (格式: YYYY-MM-DD)",
                    },
                    "event_time": {
                        "type": "string",
                        "description": "具体时间点或区间 (如: '14:00' 或 '09:30-11:30'，若无则留空)",
                    },
                    "advance_days": {
                        "type": "integer",
                        "description": "提前几天开始在简报中预警提醒 (默认 3 天)",
                    },
                    "action_items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "提取出的具体行动项 (如 ['准备汇报 PPT', '核对差旅票据'])",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["P0", "P1", "P2"],
                        "description": "优先级 (P0=生死攸关紧急, P1=重要待办, P2=常规提醒)",
                    },
                    "tldr": {
                        "type": "string",
                        "description": "日程背景一句话说明",
                    },
                },
                "required": ["email_uid", "title", "event_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_draft",
            "description": "在 Gmail 草稿箱为用户拟定一封草稿邮件（遵循安全原则：草稿不会直接发出，仅供用户后续审阅发送）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "收件人邮箱地址列表",
                    },
                    "subject": {
                        "type": "string",
                        "description": "邮件主题",
                    },
                    "body": {
                        "type": "string",
                        "description": "拟定的邮件正文内容",
                    },
                    "in_reply_to_uid": {
                        "type": "string",
                        "description": "若是回复已有邮件，提供原邮件 UID（自动提取 Message-ID 进行 Thread 关联）",
                    },
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_emails",
            "description": "在邮箱中自由搜索邮件（支持关键词、发件人过滤、只看未读等），用于按需翻找历史邮件或关联信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或 Gmail 搜索语法 (如 '账单', '发票', 'subject:周报')",
                    },
                    "sender": {
                        "type": "string",
                        "description": "按发件人过滤 (如 'service@aliyun.com')",
                    },
                    "unread_only": {
                        "type": "boolean",
                        "description": "是否仅检索未读邮件",
                    },
                    "folder": {
                        "type": "string",
                        "description": "检索的文件夹名称 (默认 'INBOX')",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回数量 (默认 10 封)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_user_preference",
            "description": "保存或更新用户的个人邮件处理偏好规则（记忆系统）。当发现用户固定习惯时调用，未来批次与日常巡检会自动遵循。",
            "parameters": {
                "type": "object",
                "properties": {
                    "condition": {
                        "type": "string",
                        "description": "偏好触发条件描述 (例如: '发件人为 noreply@github.com' 或 '主题含电费账单')",
                    },
                    "action_rule": {
                        "type": "string",
                        "description": "执行的处理动作 (例如: '归档至系统通知目录并标记已读' 或 '星标置顶提醒')",
                    },
                    "reason": {
                        "type": "string",
                        "description": "保存偏好的背景或原因说明",
                    },
                },
                "required": ["condition", "action_rule"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_user_preferences",
            "description": "查看当前已保存的所有用户偏好规则列表。",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rescue_from_spam",
            "description": "将误判进入垃圾箱 (Spam) 的邮件解救并放回收件箱或指定正常分类目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_uid": {
                        "type": "string",
                        "description": "邮件 UID",
                    },
                    "target_folder": {
                        "type": "string",
                        "description": "放回的目标文件夹 (默认 'INBOX'，或 '商业推广'/'系统通知')",
                    },
                    "category": {
                        "type": "string",
                        "enum": [
                            "important",
                            "finance_banking",
                            "government_affairs",
                            "verification_code",
                            "schedule",
                            "marketing",
                            "newsletter_system",
                        ],
                        "description": "解救后的归属分类",
                    },
                    "reason": {
                        "type": "string",
                        "description": "判断为误杀的原因",
                    },
                },
                "required": ["email_uid"],
            },
        },
    },
]


def resolve_folder_name(client: GmailClient, folder_alias: str) -> str:
    """
    将模型传入的易读分类或别名（如'商业推广'、'Spam'）映射到 Gmail 服务端真实的 IMAP 文件夹名。
    例如 Gmail 中文环境的商业推广文件夹名为 mUTF-7 编码的 '&V4NXPpCu-'。
    """
    alias_lower = (folder_alias or "").strip().lower()
    mapping = {
        "商业推广": client.get_promotions_folder_name,
        "推广": client.get_promotions_folder_name,
        "marketing": client.get_promotions_folder_name,
        "promotions": client.get_promotions_folder_name,
        "系统通知": client.get_notifications_folder_name,
        "通知": client.get_notifications_folder_name,
        "notifications": client.get_notifications_folder_name,
        "newsletter_system": client.get_notifications_folder_name,
        "spam": client.get_spam_folder_name,
        "垃圾邮件": client.get_spam_folder_name,
        "垃圾箱": client.get_spam_folder_name,
        "[gmail]/spam": client.get_spam_folder_name,
        "trash": client.get_trash_folder_name,
        "回收站": client.get_trash_folder_name,
        "废纸篓": client.get_trash_folder_name,
        "[gmail]/trash": client.get_trash_folder_name,
        "drafts": client.get_drafts_folder_name,
        "草稿": client.get_drafts_folder_name,
        "草稿箱": client.get_drafts_folder_name,
        "[gmail]/drafts": client.get_drafts_folder_name,
        "inbox": lambda: "INBOX",
        "收件箱": lambda: "INBOX",
    }
    getter = mapping.get(alias_lower)
    if getter:
        return getter()
    return folder_alias


# ==========================================
# 独立工具处理函数 (Decomposed Tool Handlers)
# ==========================================


def _handle_move_emails(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """处理批量移动邮件"""
    client = context.client
    tracker = context.tracker
    uids = [str(u) for u in arguments.get("email_uids", [])]
    target_raw = arguments.get("target_folder", "")
    category = arguments.get("category", "")
    tldr = arguments.get("tldr", "")
    resolved_dest = resolve_folder_name(client, target_raw)

    moved_count = 0
    if client.imap and uids:
        if resolved_dest == client.get_spam_folder_name():
            moved_count = client.move_to_spam(uids)
            category = category or "spam"
            tracker.spams_moved_count += moved_count
        elif resolved_dest == client.get_trash_folder_name():
            moved_count = client.move_to_trash(uids)
            category = category or "spam"
        else:
            moved_count = client.archive_emails(uids, folder_name=resolved_dest)
            if "商业推广" in mutf7_decode(resolved_dest) or category == "marketing":
                category = category or "marketing"
                tracker.marketings_moved_count += moved_count
            else:
                category = category or "newsletter_system"
                tracker.systems_moved_count += moved_count
    else:
        moved_count = len(uids)

    for uid in uids:
        tracker.mark_triaged(uid, category=category or "newsletter_system", tldr=tldr)

    return {
        "status": "success",
        "moved_count": moved_count,
        "target_folder": mutf7_decode(resolved_dest),
        "uids": uids,
    }


def _handle_read_email_content(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """处理深度读取邮件全文"""
    client = context.client
    tracker = context.tracker
    uid = str(arguments.get("email_uid", ""))
    max_len = int(arguments.get("max_length", 4000))

    if client.imap:
        return client.read_email_content(email_uid=uid, max_length=max_len)

    cached = tracker.email_map.get(uid, {})
    return {
        "status": "success",
        "uid": uid,
        "subject": cached.get("subject", "Mock Subject"),
        "from": cached.get("from", "Mock Sender"),
        "body": cached.get("snippet", "Mock Snippet Body"),
        "attachments": [],
    }


def _handle_mark_email_flags(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """处理标记邮件状态（已读/未读/加星标）"""
    client = context.client
    tracker = context.tracker
    uids = [str(u) for u in arguments.get("email_uids", [])]
    is_read = arguments.get("is_read")
    is_starred = arguments.get("is_starred")
    category = arguments.get("category", "important")
    tldr = arguments.get("tldr", "")

    res = {"status": "success", "modified_count": len(uids)}
    if client.imap and uids:
        res = client.mark_email_flags(uids, is_read=is_read, is_starred=is_starred)

    for uid in uids:
        tracker.mark_triaged(uid, category=category, tldr=tldr, priority="P1" if is_starred else "P2")

    return res


def _handle_create_calendar_event(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """处理提取日程并保存至待办日历池"""
    tracker = context.tracker
    memory = context.memory
    uid = str(arguments.get("email_uid", ""))
    title = arguments.get("title", "")
    event_date = arguments.get("event_date", "")
    event_time = arguments.get("event_time", "")
    advance_days = int(arguments.get("advance_days", 3))
    action_items = arguments.get("action_items", [])
    priority = arguments.get("priority", "P1")
    tldr = arguments.get("tldr", title)

    cached = tracker.email_map.get(uid, {})
    sched_item = {
        "message_id": cached.get("message_id", f"uid_{uid}"),
        "subject": cached.get("subject", title),
        "from": cached.get("from", ""),
        "tldr": tldr,
        "action_items": action_items,
        "event_time": event_time,
        "event_date": event_date,
        "advance_days": advance_days,
        "priority": priority,
    }
    memory.add_schedule(sched_item)
    tracker.mark_triaged(
        uid,
        category="schedule",
        tldr=tldr,
        priority=priority,
        event_date=event_date,
        event_time=event_time,
        action_items=action_items,
    )
    return {
        "status": "success",
        "message": f"日程已成功添加到日历待办池: {title} ({event_date} {event_time})",
        "schedule": sched_item,
    }


def _handle_create_draft(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """处理创建邮件草稿"""
    client = context.client
    tracker = context.tracker
    to = arguments.get("to", [])
    subject = arguments.get("subject", "")
    body = arguments.get("body", "")
    in_reply_to_uid = str(arguments.get("in_reply_to_uid", ""))
    in_reply_msg_id = ""
    if in_reply_to_uid and in_reply_to_uid in tracker.email_map:
        in_reply_msg_id = tracker.email_map[in_reply_to_uid].get("message_id", "")

    if client.imap:
        draft_res = client.create_draft(to=to, subject=subject, body=body, in_reply_to=in_reply_msg_id)
    else:
        draft_res = {"status": "success", "message": f"[Mock] 草稿已保存: {subject}", "to": to, "subject": subject}

    tracker.created_drafts.append({"to": to, "subject": subject, "body": body})
    return draft_res


def _handle_search_emails(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """处理邮件搜索检索"""
    client = context.client
    query = arguments.get("query", "")
    sender = arguments.get("sender", "")
    unread_only = bool(arguments.get("unread_only", False))
    folder = arguments.get("folder", "INBOX")
    limit = int(arguments.get("limit", 10))

    if client.imap:
        results = client.search_emails(query=query, folder=folder, unread_only=unread_only, sender=sender, limit=limit)
        return {"status": "success", "count": len(results), "emails": results}
    return {"status": "success", "count": 0, "emails": []}


def _handle_save_user_preference(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """处理持久化保存用户个人偏好"""
    memory = context.memory
    cond = arguments.get("condition", "")
    rule = arguments.get("action_rule", "")
    reason = arguments.get("reason", "")
    item = memory.add_user_preference(condition=cond, action_rule=rule, reason=reason)
    return {
        "status": "success",
        "message": f"偏好规则已持久化保存: [{cond}] => [{rule}]",
        "preference": item,
    }


def _handle_list_user_preferences(_arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """处理查看已存用户偏好列表"""
    prefs = context.memory.get_user_preferences()
    return {"status": "success", "total": len(prefs), "preferences": prefs}


def _handle_rescue_from_spam(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """处理从垃圾箱解救误判邮件"""
    client = context.client
    tracker = context.tracker
    uid = str(arguments.get("email_uid", ""))
    target = arguments.get("target_folder", "INBOX")
    cat = arguments.get("category", "important")
    reason = arguments.get("reason", "")
    resolved = resolve_folder_name(client, target)

    if client.imap:
        client.rescue_from_spam(email_uid=uid, target_folder=resolved)

    tracker.mark_triaged(uid, category=cat, tldr=f"[误杀解救] {reason}", priority="P1")
    cached = tracker.email_map.get(uid, {})
    tracker.rescued_items.append({
        "uid": uid,
        "subject": cached.get("subject", "误杀邮件"),
        "from": cached.get("from", ""),
        "category": cat,
        "reason": reason,
        "destination": mutf7_decode(resolved),
    })
    return {
        "status": "success",
        "message": f"邮件 UID {uid} 已从 Spam 解救至 {mutf7_decode(resolved)}",
    }


# 分发映射表
TOOL_HANDLERS = {
    "move_emails": _handle_move_emails,
    "read_email_content": _handle_read_email_content,
    "mark_email_flags": _handle_mark_email_flags,
    "create_calendar_event": _handle_create_calendar_event,
    "create_draft": _handle_create_draft,
    "search_emails": _handle_search_emails,
    "save_user_preference": _handle_save_user_preference,
    "list_user_preferences": _handle_list_user_preferences,
    "rescue_from_spam": _handle_rescue_from_spam,
}


def execute_tool(tool_name: str, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """统一工具执行分发器：查表调用独立 Handler"""
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        return {"status": "error", "message": f"未知工具名: {tool_name}"}
    try:
        return handler(arguments, context)
    except Exception as e:
        return {"status": "error", "message": f"执行工具 {tool_name} 异常: {e}"}
