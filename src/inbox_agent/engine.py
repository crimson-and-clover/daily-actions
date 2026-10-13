"""
Inbox Agent 智能决策与 ReAct 多轮工具调用引擎 (Engine)
驱动 Agent 在每个 Batch 开启独立上下文，依据用户偏好自主规划并调用工具处理邮件
"""

import json
import sys
from typing import Any

from openai import OpenAI

from inbox_agent.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_MODEL,
    DEEPSEEK_TIMEOUT,
    MAX_AGENT_TURNS,
    MAX_CHAT_TURNS,
)
from inbox_agent.tools import AGENT_TOOLS, ToolContext, execute_tool
from utils.json_parser import parse_json_safely
from utils.timezone import get_bjt_date_str, get_bjt_weekday_str


def build_system_prompt(user_email: str, preferences_str: str) -> str:
    """构建批次处理 System Prompt，注入时间、用户偏好与操作准则"""
    current_date = get_bjt_date_str()
    current_weekday = get_bjt_weekday_str()

    return f"""你是一个高效、审慎、具备完全自主决策权的收件箱智能管家 (Inbox Agent)。
当前时间: {current_date} ({current_weekday})
用户账号: {user_email or '本人邮箱'}

你的目标是协助用户高效整理收件箱，清理营销推广，提炼重要会议日程与关键待办，并遵循用户的个人习惯。

【核心行为准则】
1. 绝对安全原则：
   - 绝不物理删除任何邮件！
   - 商业营销/促销/导购邮件 -> 批量调用 `move_emails` 归档至'商业推广'。
   - 系统通知/服务账单/GitHub 动态/内部CI报告 -> 批量调用 `move_emails` 归档至'系统通知'。
   - 恶意垃圾/欺诈邮件 -> 调用 `move_emails` 移入 'Spam' (垃圾箱)。
   - 重要来信/政务公函/不可确定的信件 -> 严格留在 INBOX 收件箱，可调用 `mark_email_flags` 加星标置顶。
2. 日程与待办感知：
   - 邮件若包含明确会议、差旅航班、还款截期 (DDL) 等事项，务必调用 `create_calendar_event` 建立提醒，并留在 INBOX。
3. 深入探查 (深读)：
   - 初始给出的邮件仅有简短 snippet。若邮件疑似重要合作、复杂账单、会议日程且 snippet 信息不完整，可主动调用 `read_email_content` 读取完整正文后再做决策。
4. 草稿先行：
   - 若用户邮件需要礼貌回复或确认，可调用 `create_draft` 拟定草稿备用。
5. 优先批量操作：
   - 发现多封属于同类的邮件时，尽量在一次 `move_emails` 中传入多个 UID 批量转移，提升效率。

【已持久化的用户个人偏好规则库】
{preferences_str}
（注：上述规则库优先级高于默认分类规则，若邮件匹配触发条件，请严格优先执行该准则；若处理过程中发现用户有新的固定偏好，可调用 `save_user_preference` 进行持久化。）
"""


def build_batch_user_prompt(batch_emails: list[dict], batch_num: int, total_batches: int) -> str:
    """构建单批次 10 封邮件的快照输入"""
    lines = [
        f"请审阅并处理以下待办邮件批次 [批次 {batch_num}/{total_batches}]（共 {len(batch_emails)} 封）：\n"
    ]
    for idx, e in enumerate(batch_emails, 1):
        uid = str(e.get("uid", ""))
        subject = e.get("subject", "无主题")
        sender = e.get("from", "未知发件人")
        date_str = e.get("date", "")
        snippet = (e.get("snippet", "") or "").replace("\r", " ").replace("\n", " ").strip()
        lines.append(f"{idx}. [UID: {uid}] 发件人: {sender} | 日期: {date_str} | 主题: {subject}")
        if snippet:
            lines.append(f"   摘要: {snippet[:200]}")
    lines.append("\n请依据邮件特征与用户偏好，自主决策并调用相应的工具完成这批邮件的分类、归档、日程提取或标记。")
    return "\n".join(lines)


class AgentEngine:
    """基于 ReAct 多轮工具调用的邮件 Agent 引擎"""

    def __init__(
        self,
        api_key: str = DEEPSEEK_API_KEY,
        model: str = DEEPSEEK_MODEL,
        timeout: float = DEEPSEEK_TIMEOUT,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.client = None
        if self.api_key:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url="https://api.deepseek.com",
                timeout=self.timeout,
                max_retries=2,
            )

    def run_batch_triage(
        self,
        batch_emails: list[dict],
        batch_num: int,
        total_batches: int,
        context: ToolContext,
        user_email: str = "",
        max_turns: int = MAX_AGENT_TURNS,
    ) -> str:
        """
        单批次独立会话运行：
        1. 注册这批邮件到 tracker
        2. 注入全局偏好与 System Prompt
        3. 进行 ReAct 多轮工具调用闭环
        4. 兜底未归类邮件并持久化
        """
        tracker = context.tracker
        memory = context.memory
        tracker.register_batch_emails(batch_emails)

        if not self.client:
            print("[Agent Engine Warning] 离线模式：无 API KEY，按安全规则默认留存收件箱")
            for e in batch_emails:
                uid = str(e.get("uid", ""))
                tracker.mark_triaged(uid, category="important", tldr=e.get("subject", ""))
                memory.mark_processed(e.get("message_id"), is_spam=False)
            return "离线模式：已默认留存收件箱"

        prefs_str = memory.format_preferences_for_prompt()
        sys_prompt = build_system_prompt(user_email=user_email, preferences_str=prefs_str)
        user_prompt = build_batch_user_prompt(batch_emails, batch_num, total_batches)

        # 全新独立上下文
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ]

        final_summary = ""
        turn = 0

        while turn < max_turns:
            turn += 1
            if context.client.imap:
                context.client.noop()

            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=AGENT_TOOLS,
                    tool_choice="auto",
                    temperature=0.1,
                )
            except Exception as e:
                print(f"[Agent Engine Turn {turn} Error] API 调用失败: {e}", file=sys.stderr)
                break

            choice = resp.choices[0]
            msg = choice.message
            content = msg.content or ""
            tool_calls = msg.tool_calls or []

            # 将 assistant 消息载入历史
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            if content:
                assistant_msg["content"] = content
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ]
            messages.append(assistant_msg)

            # 如果没有工具调用，说明 Agent 已思考完毕并给出最终总结
            if not tool_calls:
                final_summary = content
                break

            # 遍历并执行每个工具调用
            print(f"  [Turn {turn}] Agent 发起 {len(tool_calls)} 个工具调用:")
            for tc in tool_calls:
                fn_name = tc.function.name
                raw_args = tc.function.arguments
                parsed_args = parse_json_safely(raw_args) or {}
                print(f"    -> 调用工具 `{fn_name}`: {list(parsed_args.keys())}")

                tool_result = execute_tool(fn_name, parsed_args, context)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(tool_result, ensure_ascii=False),
                })

        # 兜底保障：检查本批次中是否有被 Agent 遗漏的邮件
        for e in batch_emails:
            uid = str(e.get("uid", ""))
            m_id = e.get("message_id", "")
            cat = tracker.triage_status.get(uid)
            if not cat:
                # 遗漏的邮件默认安全留在 INBOX，归入 important
                tracker.mark_triaged(uid, category="important", tldr=e.get("subject", "留存待办"))
                cat = "important"
            memory.mark_processed(m_id, is_spam=(cat == "spam"))

        return final_summary or "本批次邮件处置完成。"

    def run_interactive_turn(
        self,
        conversation_history: list[dict],
        user_input: str,
        context: ToolContext,
        user_email: str = "",
        max_turns: int = MAX_CHAT_TURNS,
    ) -> str:
        """多轮对话模式单轮交互入口"""
        if not self.client:
            return "当前未配置 DEEPSEEK_API_KEY，无法开启大模型对话。"

        memory = context.memory
        prefs_str = memory.format_preferences_for_prompt()

        if not conversation_history:
            sys_prompt = build_system_prompt(user_email=user_email, preferences_str=prefs_str)
            conversation_history.append({"role": "system", "content": sys_prompt})

        conversation_history.append({"role": "user", "content": user_input})

        turn = 0
        final_answer = ""
        while turn < max_turns:
            turn += 1
            if context.client.imap:
                context.client.noop()

            resp = self.client.chat.completions.create(
                model=self.model,
                messages=conversation_history,
                tools=AGENT_TOOLS,
                tool_choice="auto",
                temperature=0.2,
            )
            msg = resp.choices[0].message
            content = msg.content or ""
            tool_calls = msg.tool_calls or []

            assistant_msg: dict[str, Any] = {"role": "assistant"}
            if content:
                assistant_msg["content"] = content
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ]
            conversation_history.append(assistant_msg)

            if not tool_calls:
                final_answer = content
                break

            for tc in tool_calls:
                fn_name = tc.function.name
                parsed_args = parse_json_safely(tc.function.arguments) or {}
                print(f"  [Agent 执行工具] `{fn_name}`...")
                tool_res = execute_tool(fn_name, parsed_args, context)
                conversation_history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(tool_res, ensure_ascii=False),
                })

        return final_answer or "操作已执行完毕。"
