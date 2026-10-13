"""
Inbox Agent 智能决策与 ReAct 多轮工具调用引擎 (Engine)
驱动 Agent 在每个 Batch 开启独立上下文，依据用户偏好自主规划并调用工具处理邮件
"""

import json
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI

from inbox_agent.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_MODEL,
    DEEPSEEK_TIMEOUT,
    MAX_AGENT_TURNS,
)
from inbox_agent.tools import AGENT_TOOLS, ToolContext, execute_tool
from utils.json_parser import parse_json_safely
from utils.prompt_loader import render_prompt_template
from utils.timezone import get_bjt_date_str, get_bjt_weekday_str

PROMPTS_DIR = Path(__file__).resolve().parent / "templates" / "prompts"


def build_system_prompt(user_email: str, preferences_str: str) -> str:
    """从 Jinja2 模板渲染批次处理 System Prompt"""
    return render_prompt_template(
        PROMPTS_DIR,
        "agent_system.j2",
        current_date=get_bjt_date_str(),
        current_weekday=get_bjt_weekday_str(),
        user_email=user_email,
        preferences_str=preferences_str,
    )


def build_batch_user_prompt(batch_emails: list[dict], batch_num: int, total_batches: int) -> str:
    """从 Jinja2 模板渲染单批次 10 封邮件快照 Prompt"""
    clean_emails = []
    for e in batch_emails:
        clean_emails.append({
            "uid": str(e.get("uid", "")),
            "sender": e.get("from", "未知发件人"),
            "date": e.get("date", ""),
            "subject": e.get("subject", "无主题"),
            "snippet": (e.get("snippet", "") or "").replace("\r", " ").replace("\n", " ").strip(),
        })

    return render_prompt_template(
        PROMPTS_DIR,
        "batch_user.j2",
        batch_emails=clean_emails,
        batch_num=batch_num,
        total_batches=total_batches,
    )


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

        # 仅对已被 Agent 明确调用工具研判处置的邮件标记已处理，遗漏邮件不 mark 也不设定默认分类
        for e in batch_emails:
            uid = str(e.get("uid", ""))
            m_id = e.get("message_id", "")
            cat = tracker.triage_status.get(uid)
            if cat:
                memory.mark_processed(m_id, is_spam=(cat == "spam"))
            else:
                print(f"  [Notice] 邮件 UID {uid} (Subject: {e.get('subject')}) 未被 Agent 研判处置，保留在 INBOX 且不标记为已处理。")

        return final_summary or "本批次邮件处置完成。"
