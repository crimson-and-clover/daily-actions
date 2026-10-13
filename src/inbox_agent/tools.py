"""
Inbox Agent 工具系统 (Tools Definition & Modular Dispatcher)
定义大模型可调用的标准 Function Calling 接口，采用独立 Handler 模块化执行。
支持三元组 (category, display_name, folder_id) 标准化映射与分类组织。
"""

from dataclasses import dataclass, field
from typing import Any

from inbox_agent.imap import GmailClient
from inbox_agent.memory import InboxMemory

# ==============================================================================
# 1. 类别与文件夹规范三元组 (Category, Display Name, Folder ID Specification)
# ==============================================================================

ALLOWED_CATEGORIES = {
    "marketing",
    "newsletter_system",
    "verification_code",
    "finance_banking",
    "government_affairs",
    "spam",
    "important",
    "schedule",
}


@dataclass(frozen=True)
class CategoryFolderSpec:
    """分类、显示名称与 IMAP 文件夹标识三元组"""

    category: str
    display_name: str
    folder_id: str


def get_category_spec(category: str, client: GmailClient | None = None) -> CategoryFolderSpec:
    """
    根据 category 获取对应的三元组规范：
    - category: 核心标识枚举
    - display_name: 用户友好显示与打印名称
    - folder_id: IMAP 协议交互文件夹标识
    若不在 ALLOWED_CATEGORIES 中则抛出异常立即退出。
    """
    specs: dict[str, tuple[str, str]] = {
        "marketing": ("商业推广", client.get_promotions_folder_name() if client else "[Gmail]/Promotions"),
        "newsletter_system": ("系统通知", client.get_notifications_folder_name() if client else "[Gmail]/Updates"),
        "spam": ("垃圾邮件", client.get_spam_folder_name() if client else "[Gmail]/Spam"),
        "verification_code": ("验证码", "INBOX"),
        "finance_banking": ("银行与证券", "INBOX"),
        "government_affairs": ("政府事务", "INBOX"),
        "important": ("重要邮件", "INBOX"),
        "schedule": ("日程待办", "INBOX"),
    }

    if category not in specs:
        raise ValueError(f"未定义的分类类别: '{category}'，必须在 {sorted(list(specs.keys()))} 中")

    display_name, folder_id = specs[category]
    return CategoryFolderSpec(category=category, display_name=display_name, folder_id=folder_id)


FOLDER_TO_CATEGORY: dict[str, str] = {
    "商业推广": "marketing",
    "推广": "marketing",
    "promotions": "marketing",
    "marketing": "marketing",
    "系统通知": "newsletter_system",
    "通知": "newsletter_system",
    "notifications": "newsletter_system",
    "newsletter_system": "newsletter_system",
    "spam": "spam",
    "垃圾邮件": "spam",
    "垃圾箱": "spam",
    "[gmail]/spam": "spam",
    "trash": "spam",
    "回收站": "spam",
    "废纸篓": "spam",
    "[gmail]/trash": "spam",
    "验证码": "verification_code",
    "verification_code": "verification_code",
    "银行": "finance_banking",
    "银行与证券": "finance_banking",
    "finance_banking": "finance_banking",
    "政务": "government_affairs",
    "政府事务": "government_affairs",
    "government_affairs": "government_affairs",
    "inbox": "important",
    "收件箱": "important",
    "important": "important",
    "schedule": "schedule",
    "日程": "schedule",
}


def resolve_folder_name(client: GmailClient, folder_alias: str) -> str:
    """将易读分类别名解析为 Gmail IMAP 服务端的真实文件夹名"""
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


# ==============================================================================
# 2. 批次跟踪与工具上下文 (Batch Tracker & Tool Context)
# ==============================================================================


@dataclass
class BatchTracker:
    """追踪单批次/全局邮件处理动作与数据，用于生成分类报表"""

    # 各类别列表 (用于渲染 HTML 报告)
    schedules: list[dict] = field(default_factory=list)
    importants: list[dict] = field(default_factory=list)
    systems: list[dict] = field(default_factory=list)
    marketings: list[dict] = field(default_factory=list)
    spams: list[dict] = field(default_factory=list)
    verification_codes: list[dict] = field(default_factory=list)
    finance_bankings: list[dict] = field(default_factory=list)
    government_affairs: list[dict] = field(default_factory=list)

    # 移动统计
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
        if target_list is None:
            raise ValueError(f"未定义的分类类别: '{category}'，允许的类别为: {sorted(list(category_lists.keys()))}")

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

        if not any(item.get("uid") == uid for item in target_list):
            target_list.append(base_item)


@dataclass
class ToolContext:
    """Agent 工具执行上下文容器"""

    client: GmailClient
    memory: InboxMemory
    tracker: BatchTracker
    current_folder: str = "INBOX"
    current_batch_emails: list[dict] = field(default_factory=list)


# ==============================================================================
# 3. 工具规范定义 (Tool Schemas - Grouped by Domain)
# ==============================================================================

# 3.1 邮件处置与流转类工具 (Triage & Move)
TRIAGE_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "move_emails",
            "description": "批量将邮件归档或移动到指定的分类（支持营销推广、系统通知、垃圾邮件、验证码、银行证券、政务公函等）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_uids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要移动或分类的邮件 UID 列表，例如 ['101', '102']",
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
                        ],
                        "description": "归档分类类别：marketing (商业推广), newsletter_system (系统通知), verification_code (验证码口令), finance_banking (银行证券对账单), government_affairs (政府政务公函), spam (恶意欺诈垃圾)",
                    },
                    "target_folder": {
                        "type": "string",
                        "description": "可选的目标文件夹名称/别名（如'商业推广'、'系统通知'、'Spam'）",
                    },
                    "tldr": {
                        "type": "string",
                        "description": "对所分类邮件的简要特征/原因概括说明",
                    },
                },
                "required": ["email_uids", "category"],
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
            "name": "rescue_from_spam",
            "description": "将误判进入垃圾箱 (Spam) 的邮件解救并放回收件箱或指定正常分类目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_uid": {
                        "type": "string",
                        "description": "邮件 UID",
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
                        "description": "解救后的归属分类（默认 important）",
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

# 3.2 邮件检索与内容深度查阅类工具 (Inspection & Search)
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
]

# 3.3 日历与日程待办管理工具 (Calendar & Schedule)
CALENDAR_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": "从邮件中提取日程、会议或重要到期日 (DDL)，在日程池中创建提醒并持久化。此邮件将保留在 INBOX 中。",
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

# 3.4 草稿拟定类工具 (Draft)
DRAFT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_draft",
            "description": "在 Gmail 草稿箱拟定一封草稿邮件备用（遵循安全原则：草稿不会直接发出，仅供用户审阅发送）。",
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

# 3.5 用户偏好管理工具 (Preferences)
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

# 组合全局工具列表
AGENT_TOOLS: list[dict[str, Any]] = (
    TRIAGE_TOOLS + INSPECTION_TOOLS + CALENDAR_TOOLS + DRAFT_TOOLS + PREFERENCE_TOOLS
)


# ==============================================================================
# 4. 独立工具执行处理函数 (Tool Handlers - Grouped by Domain)
# ==============================================================================

# --- 4.1 邮件处置与流转类 Handlers ---


def _handle_move_emails(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """处理批量邮件归档与分类移动"""
    client = context.client
    tracker = context.tracker
    uids = [str(u) for u in arguments.get("email_uids", [])]
    target_raw = arguments.get("target_folder", "")
    category = arguments.get("category", "")
    tldr = arguments.get("tldr", "")

    if not category and target_raw:
        category = FOLDER_TO_CATEGORY.get(target_raw.strip().lower(), "")

    if not category:
        category = "newsletter_system"

    spec = get_category_spec(category, client)

    moved_count = 0
    if client.imap and uids:
        if spec.category == "spam":
            moved_count = client.move_to_spam(uids)
            tracker.spams_moved_count += moved_count
        elif spec.category == "marketing":
            moved_count = client.archive_emails(uids, folder_name=spec.folder_id)
            tracker.marketings_moved_count += moved_count
        elif spec.category == "newsletter_system":
            moved_count = client.archive_emails(uids, folder_name=spec.folder_id)
            tracker.systems_moved_count += moved_count
        elif spec.category == "verification_code":
            client.mark_email_flags(uids, is_read=True)
            moved_count = len(uids)
        else:
            # finance_banking, government_affairs, important, schedule
            # 安全保留在 INBOX 中
            moved_count = len(uids)
    else:
        moved_count = len(uids)
        if spec.category == "marketing":
            tracker.marketings_moved_count += moved_count
        elif spec.category == "newsletter_system":
            tracker.systems_moved_count += moved_count
        elif spec.category == "spam":
            tracker.spams_moved_count += moved_count

    for uid in uids:
        tracker.mark_triaged(uid, category=spec.category, tldr=tldr)

    print(f"  [Action] 邮件 UID {uids} 已归入 [{spec.display_name}] (IMAP: {spec.folder_id})")

    return {
        "status": "success",
        "category": spec.category,
        "display_name": spec.display_name,
        "folder_id": spec.folder_id,
        "moved_count": moved_count,
        "uids": uids,
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

    spec = get_category_spec(category, client)

    res = {"status": "success", "modified_count": len(uids)}
    if client.imap and uids:
        res = client.mark_email_flags(uids, is_read=is_read, is_starred=is_starred)

    for uid in uids:
        tracker.mark_triaged(uid, category=spec.category, tldr=tldr, priority="P1" if is_starred else "P2")

    print(f"  [Action] 邮件 UID {uids} 状态已更新并归入 [{spec.display_name}]")
    return res


def _handle_rescue_from_spam(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """处理从垃圾箱解救误判邮件"""
    client = context.client
    tracker = context.tracker
    uid = str(arguments.get("email_uid", ""))
    cat = arguments.get("category", "important")
    reason = arguments.get("reason", "")

    spec = get_category_spec(cat, client)

    if client.imap:
        client.rescue_from_spam(email_uid=uid, target_folder=spec.folder_id)

    tracker.mark_triaged(uid, category=spec.category, tldr=f"[误杀解救] {reason}", priority="P1")
    cached = tracker.email_map.get(uid, {})
    tracker.rescued_items.append({
        "uid": uid,
        "subject": cached.get("subject", "误杀邮件"),
        "from": cached.get("from", ""),
        "category": spec.category,
        "reason": reason,
        "destination": spec.display_name,
    })

    print(f"  [Action] 邮件 UID {uid} 已从 Spam 解救至 [{spec.display_name}]")
    return {
        "status": "success",
        "category": spec.category,
        "display_name": spec.display_name,
        "message": f"邮件 UID {uid} 已从 Spam 解救至 {spec.display_name}",
    }


# --- 4.2 邮件检索与内容深度查阅类 Handlers ---


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


# --- 4.3 日历与待办管理类 Handlers ---


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
    print(f"  [Action] 日程待办已创建: {title} ({event_date})")
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
    print(f"  [Action] 移除日程待办: 关键词 '{title}', 移除条数: {len(removed)}")
    return {
        "status": "success",
        "removed_count": len(removed),
        "removed_events": removed,
        "message": f"成功移除 {len(removed)} 条日程事件" if removed else "未找到匹配的日程事件",
    }


# --- 4.4 草稿拟定类 Handlers ---


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
    print(f"  [Action] 草稿已创建: {subject} -> {to}")
    return draft_res


# --- 4.5 用户偏好管理类 Handlers ---


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
    # Triage & Move
    "move_emails": _handle_move_emails,
    "mark_email_flags": _handle_mark_email_flags,
    "rescue_from_spam": _handle_rescue_from_spam,
    # Inspection & Search
    "read_email_content": _handle_read_email_content,
    "search_emails": _handle_search_emails,
    # Calendar & Schedule
    "create_calendar_event": _handle_create_calendar_event,
    "list_calendar_events": _handle_list_calendar_events,
    "remove_calendar_event": _handle_remove_calendar_event,
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
