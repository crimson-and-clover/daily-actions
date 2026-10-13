"""
Inbox Agent 工具系统 (Tools Definition & Modular Dispatcher)
基于正交三维架构设计：
1. 物理去向 (Destination): folder_id | null (promotions, notifications, spam, trash, inbox)
2. 业务语义标签 (Labels): 多值集合 (important, finance_banking, government_affairs, verification_code...)
3. 日程待办 (Schedule): 0..n 条日历事件，与物理去向和标签完全解耦独立
"""

from dataclasses import dataclass, field
from typing import Any

from inbox_agent.imap import GmailClient
from inbox_agent.memory import InboxMemory

# ==============================================================================
# 1. 规范常量与去向映射 (Specifications & Constants)
# ==============================================================================

ALLOWED_DESTINATIONS = {
    "inbox",  # 保留在收件箱
    "promotions",  # 商业推广
    "notifications",  # 系统通知资讯
    "spam",  # 垃圾邮件
    "trash",  # 废纸篓/回收站
}

ALLOWED_LABELS = {
    "important",  # 重要工作与个人来信
    "finance_banking",  # 银行与证券通知/对账单
    "government_affairs",  # 政府政务公函/税务社保
    "verification_code",  # 验证码口令
    "marketing",  # 商业营销推广 (派生标签)
    "newsletter_system",  # 系统资讯周刊 (派生标签)
    "spam",  # 恶意欺诈垃圾 (派生标签)
}


@dataclass(frozen=True)
class DestinationSpec:
    """物理归档去向规范三元组"""

    destination: str
    display_name: str
    folder_id: str


def get_destination_spec(destination: str, client: GmailClient | None = None) -> DestinationSpec:
    """
    根据 destination 标识解析为规范三元组：
    - destination: 标准枚举名 (inbox, promotions, notifications, spam, trash)
    - display_name: 用户友好显示名 (商业推广, 系统通知等)
    - folder_id: IMAP 真实文件夹标识 (支持动态自适应检测)
    """
    dest_norm = (destination or "inbox").strip().lower()
    alias_map = {
        "inbox": "inbox",
        "收件箱": "inbox",
        "promotions": "promotions",
        "商业推广": "promotions",
        "推广": "promotions",
        "marketing": "promotions",
        "notifications": "notifications",
        "系统通知": "notifications",
        "通知": "notifications",
        "newsletter_system": "notifications",
        "spam": "spam",
        "垃圾邮件": "spam",
        "垃圾箱": "spam",
        "trash": "trash",
        "回收站": "trash",
        "废纸篓": "trash",
    }
    canonical = alias_map.get(dest_norm)
    if not canonical or canonical not in ALLOWED_DESTINATIONS:
        raise ValueError(
            f"未定义的归档去向: '{destination}'，允许的去向为: {sorted(list(ALLOWED_DESTINATIONS))}"
        )

    folder_map = {
        "inbox": ("收件箱", "INBOX"),
        "promotions": ("商业推广", client.get_promotions_folder_name() if client else "[Gmail]/Promotions"),
        "notifications": ("系统通知", client.get_notifications_folder_name() if client else "[Gmail]/Updates"),
        "spam": ("垃圾邮件", client.get_spam_folder_name() if client else "[Gmail]/Spam"),
        "trash": ("回收站", client.get_trash_folder_name() if client else "[Gmail]/Trash"),
    }
    display_name, folder_id = folder_map[canonical]
    return DestinationSpec(destination=canonical, display_name=display_name, folder_id=folder_id)


def resolve_folder_name(client: GmailClient, folder_alias: str) -> str:
    """将易读分类别名解析为 Gmail IMAP 服务端的真实文件夹名"""
    spec = get_destination_spec(folder_alias, client)
    return spec.folder_id


# ==============================================================================
# 2. 批次跟踪与工具上下文 (Batch Tracker & Tool Context)
# ==============================================================================


@dataclass
class BatchTracker:
    """
    追踪单批次/全局邮件处理动作与三维数据 (去向、标签、日程)，用于生成报表
    """

    # 1. 物理归档统计
    destinations_count: dict[str, int] = field(
        default_factory=lambda: {
            "promotions": 0,
            "notifications": 0,
            "spam": 0,
            "trash": 0,
            "inbox": 0,
        }
    )
    marketings_moved_count: int = 0
    systems_moved_count: int = 0
    spams_moved_count: int = 0

    # 2. 语义标签索引 {label: list[dict]}
    labeled_emails: dict[str, list[dict]] = field(
        default_factory=lambda: {
            "important": [],
            "finance_banking": [],
            "government_affairs": [],
            "verification_code": [],
            "marketing": [],
            "newsletter_system": [],
            "spam": [],
        }
    )

    # 3. 日程池列表
    schedules: list[dict] = field(default_factory=list)

    # 邮件映射快速索引 {uid: dict}
    email_map: dict[str, dict] = field(default_factory=dict)
    # 单封邮件的综合三维决策状态 {uid: {"destination": str, "labels": set[str], "triaged": bool, "tldr": str}}
    triage_decisions: dict[str, dict] = field(default_factory=dict)

    # 草稿生成记录
    created_drafts: list[dict] = field(default_factory=list)
    # 垃圾箱解救记录
    rescued_items: list[dict] = field(default_factory=list)

    # 便捷属性访问，保证渲染器与外部调用的向后兼容：
    @property
    def importants(self) -> list[dict]:
        return self.labeled_emails.get("important", [])

    @property
    def finance_bankings(self) -> list[dict]:
        return self.labeled_emails.get("finance_banking", [])

    @property
    def government_affairs(self) -> list[dict]:
        return self.labeled_emails.get("government_affairs", [])

    @property
    def verification_codes(self) -> list[dict]:
        return self.labeled_emails.get("verification_code", [])

    @property
    def marketings(self) -> list[dict]:
        return self.labeled_emails.get("marketing", [])

    @property
    def systems(self) -> list[dict]:
        return self.labeled_emails.get("newsletter_system", [])

    @property
    def spams(self) -> list[dict]:
        return self.labeled_emails.get("spam", [])

    def register_batch_emails(self, emails: list[dict]):
        for e in emails:
            uid = str(e.get("uid", ""))
            if uid:
                self.email_map[uid] = dict(e)
                if uid not in self.triage_decisions:
                    self.triage_decisions[uid] = {
                        "destination": "inbox",
                        "labels": set(),
                        "triaged": False,
                        "tldr": "",
                    }

    def set_destination(self, uid: str, destination: str, tldr: str = ""):
        """设置邮件物理归档去向，并自动派生基础标签"""
        if uid not in self.triage_decisions:
            self.triage_decisions[uid] = {
                "destination": destination,
                "labels": set(),
                "triaged": True,
                "tldr": tldr,
            }
        decision = self.triage_decisions[uid]
        decision["destination"] = destination
        decision["triaged"] = True
        if tldr:
            decision["tldr"] = tldr

        # 统计物理计数
        self.destinations_count[destination] = self.destinations_count.get(destination, 0) + 1

        # 派生标签并加入分组索引
        derived_label_map = {
            "promotions": "marketing",
            "notifications": "newsletter_system",
            "spam": "spam",
        }
        derived_label = derived_label_map.get(destination)
        if derived_label:
            self.add_labels(uid, [derived_label], tldr=tldr)

    def add_labels(self, uid: str, labels: list[str], tldr: str = "", priority: str = "P1"):
        """为邮件追加业务语义标签"""
        for lbl in labels:
            if lbl not in ALLOWED_LABELS:
                raise ValueError(f"未定义的语义标签: '{lbl}'，允许的标签为: {sorted(list(ALLOWED_LABELS))}")

        if uid not in self.triage_decisions:
            self.triage_decisions[uid] = {
                "destination": "inbox",
                "labels": set(),
                "triaged": True,
                "tldr": tldr,
            }
        decision = self.triage_decisions[uid]
        decision["triaged"] = True
        decision["labels"].update(labels)
        if tldr:
            decision["tldr"] = tldr

        base_item = dict(self.email_map.get(uid, {"uid": uid}))
        base_item.update({
            "labels": list(decision["labels"]),
            "tldr": decision["tldr"] or base_item.get("subject", ""),
            "priority": priority,
        })

        for lbl in labels:
            lst = self.labeled_emails.setdefault(lbl, [])
            if not any(it.get("uid") == uid for it in lst):
                lst.append(base_item)

    def attach_schedule(self, uid: str, schedule_item: dict):
        """将提炼出的日程事件挂载至日程池，并标定该邮件已被处理"""
        if uid not in self.triage_decisions:
            self.triage_decisions[uid] = {
                "destination": "inbox",
                "labels": set(),
                "triaged": True,
                "tldr": "",
            }
        self.triage_decisions[uid]["triaged"] = True
        self.schedules.append(schedule_item)


@dataclass
class ToolContext:
    """Agent 工具执行上下文容器"""

    client: GmailClient
    memory: InboxMemory
    tracker: BatchTracker
    current_folder: str = "INBOX"
    current_batch_emails: list[dict] = field(default_factory=list)


# ==============================================================================
# 3. 工具规范定义 (Tool Schemas - Grouped by Orthogonal Domain)
# ==============================================================================

# 3.1 物理去向管理工具 (Destination)
DESTINATION_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "move_emails",
            "description": "批量将邮件移动到指定的归档分类文件夹（如商业推广、系统通知、Spam 垃圾邮件、Trash 回收站）。此操作仅负责物理搬运，不影响日程提取。",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_uids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要移动的邮件 UID 列表，例如 ['101', '102']",
                    },
                    "destination": {
                        "type": "string",
                        "enum": ["promotions", "notifications", "spam", "trash"],
                        "description": "目标归档去向：promotions (商业推广), notifications (系统通知资讯), spam (垃圾邮件), trash (废纸篓/回收站)",
                    },
                    "tldr": {
                        "type": "string",
                        "description": "移动归档的原因简要说明",
                    },
                },
                "required": ["email_uids", "destination"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rescue_from_spam",
            "description": "将误判进入垃圾箱 (Spam) 的邮件解救，移回指定目录并赋予语义标签。",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_uid": {
                        "type": "string",
                        "description": "邮件 UID",
                    },
                    "destination": {
                        "type": "string",
                        "enum": ["inbox", "promotions", "notifications"],
                        "description": "解救后的去向目录 (默认 'inbox')",
                    },
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "赋予的业务语义标签（如 ['important'] 或 ['finance_banking']）",
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

# 3.2 业务语义标签与状态工具 (Labels & Flags)
LABEL_AND_FLAG_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "label_emails",
            "description": "为保留在收件箱 (INBOX) 的邮件打上一个或多个业务语义标签，用于重点标识与简报分组呈送。",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_uids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "邮件 UID 列表",
                    },
                    "labels": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "important",
                                "finance_banking",
                                "government_affairs",
                                "verification_code",
                            ],
                        },
                        "description": "赋予的语义标签列表：important (重要工作来信), finance_banking (银行证券对账单), government_affairs (政府政务公函), verification_code (验证码口令)",
                    },
                    "tldr": {
                        "type": "string",
                        "description": "留存原因或要点说明",
                    },
                },
                "required": ["email_uids", "labels"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_email_flags",
            "description": "调整邮件的阅读状态或旗标星标（已读/未读、添加或取消星标置顶）。纯粹管理邮件状态，不改变归档去向与业务标签。",
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
                        "description": "是否标记星标/高优旗标 (True=加星标, False=取消星标)",
                    },
                },
                "required": ["email_uids"],
            },
        },
    },
]

# 3.3 日程与待办事件工具 (Schedule - Fully Orthogonal)
CALENDAR_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": "从邮件中提炼具体日程、会议、航班行程或还款截期 (DDL)，记录到日历待办池中并持久化。此操作独立于邮件去向（无论邮件归档还是留在收件箱均可提取日程）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_uid": {
                        "type": "string",
                        "description": "关联的邮件 UID",
                    },
                    "title": {
                        "type": "string",
                        "description": "日程标题 (如：季度战略复盘会、招行信用卡还款日)",
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
                        "description": "优先级 (P0=紧急重要, P1=重要待办, P2=常规提醒)",
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
            "name": "list_calendar_events",
            "description": "查看当前日历待办池中已记录的日程事件列表，支持按关键词检索（用于核对已有会议与改期状态）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "可选的检索关键词（如日程标题或发件人）",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_calendar_event",
            "description": "从日历待办池中移除已取消、改期重置或退订的日程事件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "要移除的日程标题或关键字（如'战略复盘会'）",
                    },
                    "event_date": {
                        "type": "string",
                        "description": "日程对应的日期 (YYYY-MM-DD)，若提供则精确匹配",
                    },
                    "email_uid": {
                        "type": "string",
                        "description": "关联的原邮件 UID（若已知）",
                    },
                },
            },
        },
    },
]

# 3.4 邮件检索与内容深度查阅类工具 (Inspection & Search)
INSPECTION_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_email_content",
            "description": "按 UID 读取单封邮件的完整正文、发件人/收件人详情以及附件信息。仅在 snippet 摘要不足以确认细节、或需深度提取会议议程/复杂账单时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_uid": {
                        "type": "string",
                        "description": "邮件 UID",
                    },
                    "folder": {
                        "type": "string",
                        "description": "邮件所在目录名称，默认当前批次所在文件夹 (如 'INBOX' 或 '[Gmail]/Spam')",
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
                        "description": "检索的文件夹名称 (默认当前批次所在文件夹)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回数量 (默认 10 封)",
                    },
                },
            },
        },
    },
]

# 3.5 草稿拟定类工具 (Draft)
DRAFT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_draft",
            "description": "在 Gmail 草稿箱拟定一封草稿邮件备用（草稿不会直接发出，仅供用户审阅发送）。",
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
]

# 3.6 用户偏好管理工具 (Preferences)
PREFERENCE_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "save_user_preference",
            "description": "保存或更新用户的个人邮件处理偏好规则（记忆系统）。当发现明确习惯规则时可持久化。",
            "parameters": {
                "type": "object",
                "properties": {
                    "condition": {
                        "type": "string",
                        "description": "偏好触发条件描述 (例如: '发件人为 noreply@github.com')",
                    },
                    "action_rule": {
                        "type": "string",
                        "description": "执行的处理动作 (例如: '归档至系统通知目录并标记已读')",
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
            "name": "remove_user_preference",
            "description": "移除指定的已保存用户偏好规则。",
            "parameters": {
                "type": "object",
                "properties": {
                    "preference_id": {
                        "type": "string",
                        "description": "要删除的偏好规则 ID (如 'pref_1234abcd')",
                    },
                },
                "required": ["preference_id"],
            },
        },
    },
]

AGENT_TOOLS: list[dict[str, Any]] = (
    DESTINATION_TOOLS
    + LABEL_AND_FLAG_TOOLS
    + CALENDAR_TOOLS
    + INSPECTION_TOOLS
    + DRAFT_TOOLS
    + PREFERENCE_TOOLS
)


# ==============================================================================
# 4. 独立工具执行处理函数 (Tool Handlers)
# ==============================================================================


def _handle_move_emails(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """处理批量邮件归档与物理移动"""
    client = context.client
    tracker = context.tracker
    uids = [str(u) for u in arguments.get("email_uids", [])]
    dest_raw = arguments.get("destination", "")
    tldr = arguments.get("tldr", "")

    spec = get_destination_spec(dest_raw, client)

    moved_count = 0
    if client.imap and uids:
        if spec.destination == "spam":
            moved_count = client.move_to_spam(uids)
            tracker.spams_moved_count += moved_count
        elif spec.destination == "promotions":
            moved_count = client.archive_emails(uids, folder_name=spec.folder_id)
            tracker.marketings_moved_count += moved_count
        elif spec.destination == "notifications":
            moved_count = client.archive_emails(uids, folder_name=spec.folder_id)
            tracker.systems_moved_count += moved_count
        elif spec.destination == "trash":
            moved_count = client.move_to_trash(uids)
        else:
            # inbox (留在收件箱)
            moved_count = len(uids)
    else:
        moved_count = len(uids)
        if spec.destination == "promotions":
            tracker.marketings_moved_count += moved_count
        elif spec.destination == "notifications":
            tracker.systems_moved_count += moved_count
        elif spec.destination == "spam":
            tracker.spams_moved_count += moved_count

    for uid in uids:
        tracker.set_destination(uid, destination=spec.destination, tldr=tldr)

    print(f"  [Action: Move] 邮件 UID {uids} 移至 [{spec.display_name}] (IMAP: {spec.folder_id})")

    return {
        "status": "success",
        "destination": spec.destination,
        "display_name": spec.display_name,
        "folder_id": spec.folder_id,
        "moved_count": moved_count,
        "uids": uids,
    }


def _handle_label_emails(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """处理给留在收件箱的邮件打语义标签"""
    client = context.client
    tracker = context.tracker
    uids = [str(u) for u in arguments.get("email_uids", [])]
    labels = arguments.get("labels", [])
    tldr = arguments.get("tldr", "")

    if not isinstance(labels, list) or not labels:
        raise ValueError("调用 label_emails 必须指定至少一个合法 labels 列表")

    # 如果标签包含验证码，自动标记已读
    if "verification_code" in labels and client.imap and uids:
        client.mark_email_flags(uids, is_read=True)

    for uid in uids:
        tracker.add_labels(uid, labels=labels, tldr=tldr)

    print(f"  [Action: Label] 邮件 UID {uids} 赋予标签 {labels}")
    return {
        "status": "success",
        "uids": uids,
        "labels": labels,
        "tldr": tldr,
    }


def _handle_mark_email_flags(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """处理标记邮件状态（已读/未读/加星标）"""
    client = context.client
    uids = [str(u) for u in arguments.get("email_uids", [])]
    is_read = arguments.get("is_read")
    is_starred = arguments.get("is_starred")

    res = {"status": "success", "modified_count": len(uids)}
    if client.imap and uids:
        res = client.mark_email_flags(uids, is_read=is_read, is_starred=is_starred)

    print(f"  [Action: Flags] 邮件 UID {uids} 状态更新: read={is_read}, starred={is_starred}")
    return res


def _handle_rescue_from_spam(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """处理从垃圾箱解救误判邮件并分配去向与标签"""
    client = context.client
    tracker = context.tracker
    uid = str(arguments.get("email_uid", ""))
    dest = arguments.get("destination", "inbox")
    labels = arguments.get("labels", ["important"])
    reason = arguments.get("reason", "")

    spec = get_destination_spec(dest, client)

    if client.imap:
        client.rescue_from_spam(email_uid=uid, target_folder=spec.folder_id)

    tracker.set_destination(uid, destination=spec.destination, tldr=f"[误杀解救] {reason}")
    tracker.add_labels(uid, labels=labels, tldr=f"[误杀解救] {reason}")

    cached = tracker.email_map.get(uid, {})
    tracker.rescued_items.append({
        "uid": uid,
        "subject": cached.get("subject", "误杀邮件"),
        "from": cached.get("from", ""),
        "destination": spec.display_name,
        "labels": labels,
        "reason": reason,
    })

    print(f"  [Action: Rescue] 邮件 UID {uid} 从 Spam 解救至 [{spec.display_name}], 标签: {labels}")
    return {
        "status": "success",
        "destination": spec.destination,
        "display_name": spec.display_name,
        "labels": labels,
        "message": f"邮件 UID {uid} 已从 Spam 解救至 {spec.display_name}",
    }


def _handle_create_calendar_event(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """处理从邮件中提炼日程事件并持久化"""
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
        "title": title,
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
    tracker.attach_schedule(uid, sched_item)

    print(f"  [Action: Schedule] 日程待办已创建: {title} ({event_date})")
    return {
        "status": "success",
        "message": f"日程已成功添加到日历待办池: {title} ({event_date} {event_time})",
        "schedule": sched_item,
    }


def _handle_list_calendar_events(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """处理查看日历池中的日程事件"""
    keyword = (arguments.get("keyword") or "").strip().lower()
    schedules = context.memory.get_active_schedules()
    if keyword:
        schedules = [
            s
            for s in schedules
            if keyword in s.get("subject", "").lower()
            or keyword in s.get("from", "").lower()
            or keyword in s.get("tldr", "").lower()
        ]
    return {
        "status": "success",
        "total": len(schedules),
        "events": schedules,
    }


def _handle_remove_calendar_event(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """处理从日历待办池中移除已取消或改期的日程"""
    memory = context.memory
    tracker = context.tracker
    title = arguments.get("title", "")
    event_date = arguments.get("event_date", "")
    uid = str(arguments.get("email_uid", ""))

    msg_id = ""
    if uid and uid in tracker.email_map:
        msg_id = tracker.email_map[uid].get("message_id", "")

    removed = memory.remove_schedule(message_id=msg_id, subject=title, event_date=event_date)
    print(f"  [Action: Schedule] 移除日程待办: 关键词 '{title}', 移除条数: {len(removed)}")
    return {
        "status": "success",
        "removed_count": len(removed),
        "removed_events": removed,
        "message": f"成功移除 {len(removed)} 条日程事件" if removed else "未找到匹配的日程事件",
    }


def _handle_read_email_content(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """处理深度读取邮件全文"""
    client = context.client
    tracker = context.tracker
    uid = str(arguments.get("email_uid", ""))
    folder = arguments.get("folder") or context.current_folder
    max_len = int(arguments.get("max_length", 4000))

    if client.imap:
        return client.read_email_content(email_uid=uid, folder=folder, max_length=max_len)

    cached = tracker.email_map.get(uid, {})
    return {
        "status": "success",
        "uid": uid,
        "subject": cached.get("subject", "Mock Subject"),
        "from": cached.get("from", "Mock Sender"),
        "body": cached.get("snippet", "Mock Snippet Body"),
        "attachments": [],
    }


def _handle_search_emails(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """处理邮件搜索检索"""
    client = context.client
    query = arguments.get("query", "")
    sender = arguments.get("sender", "")
    unread_only = bool(arguments.get("unread_only", False))
    folder = arguments.get("folder") or context.current_folder
    limit = int(arguments.get("limit", 10))

    if client.imap:
        results = client.search_emails(query=query, folder=folder, unread_only=unread_only, sender=sender, limit=limit)
        return {"status": "success", "count": len(results), "emails": results}
    return {"status": "success", "count": 0, "emails": []}


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
    print(f"  [Action: Draft] 草稿已创建: {subject} -> {to}")
    return draft_res


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


def _handle_remove_user_preference(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """处理删除用户偏好规则"""
    pref_id = arguments.get("preference_id", "")
    success = context.memory.remove_user_preference(pref_id)
    return {
        "status": "success" if success else "error",
        "message": f"偏好规则 {pref_id} 已删除" if success else f"未找到 ID 为 {pref_id} 的偏好规则",
    }


# ==============================================================================
# 5. 分发映射与执行入口 (Dispatcher & Execution)
# ==============================================================================

TOOL_HANDLERS = {
    # Destination
    "move_emails": _handle_move_emails,
    "rescue_from_spam": _handle_rescue_from_spam,
    # Labels & Flags
    "label_emails": _handle_label_emails,
    "mark_email_flags": _handle_mark_email_flags,
    # Schedule
    "create_calendar_event": _handle_create_calendar_event,
    "list_calendar_events": _handle_list_calendar_events,
    "remove_calendar_event": _handle_remove_calendar_event,
    # Inspection & Search
    "read_email_content": _handle_read_email_content,
    "search_emails": _handle_search_emails,
    # Draft
    "create_draft": _handle_create_draft,
    # Preferences
    "save_user_preference": _handle_save_user_preference,
    "list_user_preferences": _handle_list_user_preferences,
    "remove_user_preference": _handle_remove_user_preference,
}


def execute_tool(tool_name: str, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """
    统一工具执行分发器：查表调用独立 Handler。
    若类别非法或参数核心校验失败抛出 ValueError，直接向上抛出中断退出。
    """
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        raise ValueError(f"未知工具名: {tool_name}")
    try:
        return handler(arguments, context)
    except ValueError as ve:
        raise ve
    except Exception as e:
        return {"status": "error", "message": f"执行工具 {tool_name} 异常: {e}"}
