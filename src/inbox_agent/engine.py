"""
Inbox Agent 智能决策与 ReAct 多轮工具调用引擎 (Engine)
驱动 Agent 在每个 Batch 开启独立上下文，依据用户偏好自主规划并调用工具处理邮件
"""

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, TypeAdapter

from inbox_agent.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_MODEL,
    DEEPSEEK_TIMEOUT,
    MAX_AGENT_TURNS,
)
from inbox_agent.imap.models import Email
from inbox_agent.profile import load_user_profile
from inbox_agent.tools import AGENT_TOOLS, ToolContext, execute_tool
from inbox_agent.tracker import BatchTracker
from utils.json_parser import parse_json_safely
from utils.prompt_loader import render_prompt_template
from utils.timezone import get_bjt_date_str, get_bjt_weekday_str

PROMPTS_DIR = Path(__file__).resolve().parent / "templates" / "prompts"
_TOOL_JSON_ADAPTER = TypeAdapter(Any)


def build_system_prompt(user_email: str, current_code: str = "inbox") -> str:
    """从 Jinja2 模板渲染批次处理 System Prompt"""
    return render_prompt_template(
        PROMPTS_DIR,
        "agent_system.j2",
        current_date=get_bjt_date_str(),
        current_weekday=get_bjt_weekday_str(),
        user_email=user_email,
        current_code=current_code,
        user_profile=load_user_profile(),
    )


def build_batch_user_prompt(
    batch_emails: Sequence[Email],
    batch_num: int,
    total_batches: int,
    current_code: str = "inbox",
    current_date: str | None = None,
) -> str:
    """从 Jinja2 模板渲染单批次邮件快照 Prompt，附带 Message-ID 以便日程提取"""
    current_date_str = current_date or get_bjt_date_str()
    clean_emails = []
    for e in batch_emails:
        text_source = e.body or e.snippet or ""
        clean_snippet = text_source.replace("\r", " ").replace("\n", " ").strip()[:2000]
        clean_emails.append({
            "uid": str(e.uid),
            "sender": e.from_addr,
            "date": e.date_str if hasattr(e, "date_str") else str(e.date),
            "subject": e.subject,
            "message_id": e.message_id,
            "snippet": clean_snippet,
        })

    return render_prompt_template(
        PROMPTS_DIR,
        "batch_user.j2",
        batch_emails=clean_emails,
        batch_num=batch_num,
        total_batches=total_batches,
        current_code=current_code,
        current_date=current_date_str,
    )


class AgentEngine:
    """基于 ReAct 多轮工具调用的邮件智能分流与处置引擎"""

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
        batch_emails: Sequence[Email],
        batch_num: int,
        total_batches: int,
        context: ToolContext,
        user_email: str = "",
        max_turns: int = MAX_AGENT_TURNS,
        tracker: BatchTracker | None = None,
    ) -> str:
        """
        单批次独立 ReAct 会话运行 (纯净 Email 强类型实体模型)：
        1. 注入当前批次邮件实体列表至 context.current_emails
        2. 建立基于全局不可变 Message-ID 的状态追踪
        3. 渲染 System 与 User Prompts 开启全新上下文
        4. 进行 ReAct 多轮工具调用闭环与保活
        5. 严格按实际处置结果持久化已处理状态至 memory
        6. 若传入 tracker，则同步收集处置决策与报表数据
        """
        if tracker:
            tracker.register_batch_emails(batch_emails)

        # 挂载当前批次邮件实体列表至 ToolContext 供各工具即时访问与元数据提取
        context.current_emails = list(batch_emails)
        # 每批上下文独立，上一批的日程查询不能作为本批操作的依据。
        context.calendar_checked = False
        context.fully_read_emails.clear()
        memory = context.memory

        # 建立当前批次按 Message-ID 索引的垃圾状态映射
        msg_id_spam_map: dict[str, bool] = {
            e.message_id: (context.current_code == "spam") for e in batch_emails if e.message_id
        }

        if not self.client:
            print("[Agent Engine Warning] 离线模式：无 API KEY，本批次跳过处置且不记录已处理状态")
            return "离线模式：跳过本批次"

        sys_prompt = build_system_prompt(user_email=user_email, current_code=context.current_code)
        user_prompt = build_batch_user_prompt(
            batch_emails,
            batch_num,
            total_batches,
            current_code=context.current_code,
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ]

        final_summary = ""
        turn = 0
        dispositioned_msg_ids: set[str] = set()
        reconcile_attempted = False

        while turn < max_turns:
            turn += 1
            # 只认可本轮开始前已加入上下文的查询结果，禁止首次查询与变更在同轮放行。
            calendar_checked_at_turn_start = context.calendar_checked
            read_snapshot = dict(context.fully_read_emails)
            if context.connection and context.connection.is_connected():
                try:
                    context.connection.noop()
                except Exception:
                    pass

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

            # 如果没有工具调用，先检查本批次是否所有邮件均已确立去向
            if not tool_calls:
                unhandled_emails = [e for e in batch_emails if e.message_id not in dispositioned_msg_ids]
                # 若存在尚未明确去向的邮件、尚未催促对账且未达轮次上限，主动对账催促模型补全处置 (最多追问 1 次防死循环)
                if unhandled_emails and not reconcile_attempted and turn < max_turns:
                    reconcile_attempted = True
                    unhandled_list = [f"- [UID: {e.uid}] 主题: {e.subject}" for e in unhandled_emails]
                    reminder = (
                        f"当前批次中仍有 {len(unhandled_emails)} 封待办邮件尚未调用工具明确去向：\n"
                        + "\n".join(unhandled_list)
                        + "\n请先按系统规则调用 `read_email_content` 完整阅读尚未读全的邮件，再为具备操作条件的邮件调用 `route_emails` 明确处置去向。"
                        "每封邮件只能选择一个 destination；保留收件箱使用 `route_emails(email_uids=[...], destination='inbox', tldr='...')`，确认垃圾则选择 spam。"
                        "读取失败或仍被截断的邮件可保留未决并说明原因，不得为完成批次而绕过全文阅读；"
                        "学校活动邀请、可选报名等不符合日程准入规则的邮件只做分类，不得为补齐处置而创建日程。"
                    )
                    messages.append({"role": "user", "content": reminder})
                    continue

                final_summary = content
                break

            # 遍历并执行当前轮次产生的所有工具调用
            print(f"  [Turn {turn}] Agent 发起 {len(tool_calls)} 个工具调用:")
            for tc in tool_calls:
                fn_name = tc.function.name
                raw_args = tc.function.arguments

                # 严格防御参数被解析为 list 导致 .keys() 报错
                parsed_raw = parse_json_safely(raw_args)
                parsed_args = parsed_raw if isinstance(parsed_raw, dict) else {}
                print(f"    -> 调用工具 `{fn_name}`: {list(parsed_args.keys())}")

                if fn_name in {"create_calendar_event", "remove_calendar_event"} and not calendar_checked_at_turn_start:
                    tool_result = {
                        "status": "error",
                        "code": "calendar_check_required",
                        "message": "本轮开始前尚未收到日程查询结果。请先调用 list_calendar_events，等待结果并核对，再在后续轮次重试；同批次后续操作可复用结果。",
                    }
                else:
                    tool_result = execute_tool(fn_name, parsed_args, context, read_snapshot=read_snapshot)

                # 仅当 route_emails 成功执行时，才确立邮件的最终去向并加入持久化集合
                if tool_result.get("status") == "success":
                    if fn_name == "route_emails":
                        destination = tool_result["destination"]
                        tldr = parsed_args.get("tldr", "")
                        message_ids = [item["message_id"] for item in tool_result["affected_emails"]]
                        for message_id in message_ids:
                            dispositioned_msg_ids.add(message_id)
                            msg_id_spam_map[message_id] = destination == "spam"
                        if tracker:
                            tracker.record_route(
                                message_ids=message_ids,
                                destination=destination,
                                tldr=tldr,
                                source_code=tool_result["source_code"],
                            )
                    elif fn_name == "create_calendar_event" and tracker:
                        if tool_result.get("schedule"):
                            tracker.record_schedule(tool_result["schedule"])
                    elif fn_name == "create_email_draft" and tracker:
                        if tool_result.get("draft"):
                            tracker.record_draft(tool_result["draft"])

                if isinstance(tool_result, BaseModel):
                    tool_content = tool_result.model_dump_json()
                else:
                    tool_content = _TOOL_JSON_ADAPTER.dump_json(tool_result).decode("utf-8")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_content,
                })

        # 批次提交持久化状态：
        # 严格基于 dispositioned_msg_ids（仅经 route_emails 成功处置并确立去向的邮件）入库
        # 彻底杜绝工具调用失败中途退出时未处置邮件被误标为已处理
        submitted_count = 0
        for e in batch_emails:
            if e.message_id and e.message_id in dispositioned_msg_ids:
                memory.mark_processed(e.message_id, is_spam=msg_id_spam_map.get(e.message_id, False))
                submitted_count += 1

        # 批次收尾显式落盘保存加密状态 (Fail-Safe 权威持久化)
        memory.save()

        if turn >= max_turns and len(dispositioned_msg_ids) < len(batch_emails):
            return f"批次已达最大思考轮次 ({max_turns})，已完成处置 {submitted_count}/{len(batch_emails)} 封邮件。"

        return final_summary or f"本批次邮件处置完成 (已处置 {submitted_count}/{len(batch_emails)} 封)。"
