"""
Inbox Agent 工具系统 (Tools Definition & Dispatcher)
定义大模型可调用的标准 Function Calling 接口及执行逻辑
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

        if category == "schedule":
            # 避免重复
            if not any(s.get("uid") == uid for s in self.schedules):
                self.schedules.append(base_item)
        elif category == "important":
            if not any(s.get("uid") == uid for s in self.importants):
                self.importants.append(base_item)
        elif category == "newsletter_system":
            if not any(s.get("uid") == uid for s in self.systems):
                self.systems.append(base_item)
        elif category == "marketing":
            if not any(s.get("uid") == uid for s in self.marketings):
                self.marketings.append(base_item)
        elif category == "spam":
            if not any(s.get("uid") == uid for s in self.spams):
                self.spams.append(base_item)


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
            "description": "批量将邮件移动到指定的归档分类文件夹（如商业推广、系统通知、[Gmail]/Spam 垃圾邮件、[Gmail]/Trash 回收站等）。系统会自动解析别名（如传入'商业推广'会自动匹配 Gmail 对应文件夹）。",
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
                        "enum": ["marketing", "newsletter_system", "spam", "archive"],
                        "description": "归档分类类别：marketing (商业推广营销), newsletter_system (系统通知资讯), spam (恶意/诈骗垃圾邮件), archive (常规归档)",
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
            "description": "标记邮件状态，支持标记已读/未读、或添加星标置顶（Starred/Flagged）。对于重要来信、政务通讯或需要用户重点留意的邮件，加星标置顶并留在 INBOX。",
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
                        "enum": ["important", "schedule"],
                        "description": "邮件分类类别（通常为 important 重要来信）",
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
            "description": "在邮箱中自由搜索邮件（支持关键词、发件人过滤、只看未读等），用于多轮对话中按需翻找历史邮件或关联信息。",
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
            "description": "保存或更新用户的个人邮件处理偏好规则（记忆系统）。当用户明确提出习惯（如'来自 GitHub 的通知直接放系统通知并标已读'）时调用，未来批次与运行会自动遵循。",
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
                        "enum": ["important", "schedule", "marketing", "newsletter_system"],
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
    """将口语化别名或常见分类映射为真实的 Gmail IMAP 文件夹名"""
    f_lower = (folder_alias or "").strip().lower()
    if f_lower in ["商业推广", "推广", "marketing", "promotions"]:
        return client.get_promotions_folder_name()
    elif f_lower in ["系统通知", "通知", "notifications", "newsletter_system"]:
        return client.get_notifications_folder_name()
    elif f_lower in ["spam", "垃圾邮件", "垃圾箱", "[gmail]/spam"]:
        return client.get_spam_folder_name()
    elif f_lower in ["trash", "回收站", "废纸篓", "废件箱", "[gmail]/trash"]:
        return client.get_trash_folder_name()
    elif f_lower in ["drafts", "草稿", "草稿箱", "[gmail]/drafts"]:
        return client.get_drafts_folder_name()
    elif f_lower in ["inbox", "收件箱"]:
        return "INBOX"
    return folder_alias


def execute_tool(tool_name: str, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """统一工具执行分发器"""
    client = context.client
    memory = context.memory
    tracker = context.tracker

    try:
        if tool_name == "move_emails":
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

            # 更新 tracker
            for uid in uids:
                tracker.mark_triaged(uid, category=category or "newsletter_system", tldr=tldr)

            return {
                "status": "success",
                "moved_count": moved_count,
                "target_folder": mutf7_decode(resolved_dest),
                "uids": uids,
            }

        elif tool_name == "read_email_content":
            uid = str(arguments.get("email_uid", ""))
            max_len = int(arguments.get("max_length", 4000))
            if client.imap:
                return client.read_email_content(email_uid=uid, max_length=max_len)
            else:
                # 离线或 mock 数据返回
                cached = tracker.email_map.get(uid, {})
                return {
                    "status": "success",
                    "uid": uid,
                    "subject": cached.get("subject", "Mock Subject"),
                    "from": cached.get("from", "Mock Sender"),
                    "body": cached.get("snippet", "Mock Snippet Body"),
                    "attachments": [],
                }

        elif tool_name == "mark_email_flags":
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

        elif tool_name == "create_calendar_event":
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

        elif tool_name == "create_draft":
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

        elif tool_name == "search_emails":
            query = arguments.get("query", "")
            sender = arguments.get("sender", "")
            unread_only = bool(arguments.get("unread_only", False))
            folder = arguments.get("folder", "INBOX")
            limit = int(arguments.get("limit", 10))

            if client.imap:
                results = client.search_emails(query=query, folder=folder, unread_only=unread_only, sender=sender, limit=limit)
                return {"status": "success", "count": len(results), "emails": results}
            else:
                return {"status": "success", "count": 0, "emails": []}

        elif tool_name == "save_user_preference":
            cond = arguments.get("condition", "")
            rule = arguments.get("action_rule", "")
            reason = arguments.get("reason", "")
            item = memory.add_user_preference(condition=cond, action_rule=rule, reason=reason)
            return {
                "status": "success",
                "message": f"偏好规则已持久化保存: [{cond}] => [{rule}]",
                "preference": item,
            }

        elif tool_name == "list_user_preferences":
            prefs = memory.get_user_preferences()
            return {"status": "success", "total": len(prefs), "preferences": prefs}

        elif tool_name == "rescue_from_spam":
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

        else:
            return {"status": "error", "message": f"未知工具名: {tool_name}"}

    except Exception as e:
        return {"status": "error", "message": f"执行工具 {tool_name} 异常: {e}"}
