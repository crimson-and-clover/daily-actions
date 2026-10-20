"""
Inbox Agent 智能决策与 ReAct 多轮工具调用引擎 (Engine)
驱动 Agent 在每个 Batch 开启独立上下文，依据用户偏好自主规划并调用工具处理邮件
"""

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from openai import OpenAI

from inbox_agent.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_MODEL,
    DEEPSEEK_TIMEOUT,
    MAX_AGENT_TURNS,
)
from inbox_agent.imap.models import Email
from inbox_agent.tools import AGENT_TOOLS, ToolContext, execute_tool
from inbox_agent.tracker import BatchTracker
from utils.json_parser import parse_json_safely
from utils.prompt_loader import render_prompt_template
from utils.timezone import get_bjt_date_str, get_bjt_weekday_str

PROMPTS_DIR = Path(__file__).resolve().parent / "templates" / "prompts"


def build_system_prompt(user_email: str, current_code: str = "inbox") -> str:
    """从 Jinja2 模板渲染批次处理 System Prompt"""
    return render_prompt_template(
        PROMPTS_DIR,
        "agent_system.j2",
        current_date=get_bjt_date_str(),
        current_weekday=get_bjt_weekday_str(),
        user_email=user_email,
        current_code=current_code,
    )


def build_batch_user_prompt(
    batch_emails: Sequence[Email],
    batch_num: int,
    total_batches: int,
    current_code: str = "inbox",
) -> str:
    """从 Jinja2 模板渲染单批次邮件快照 Prompt，附带 Message-ID 以便日程提取"""
    clean_emails = []
    for e in batch_emails:
        text_source = e.body or e.snippet or ""
        clean_snippet = text_source.replace("\r", " ").replace("\n", " ").strip()[:2000]
        clean_emails.append({
            "uid": str(e.uid),
            "sender": e.from_addr,
            "date": e.date,
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
        1. 注入当前批次邮件字典数据至 context.current_emails
        2. 建立基于全局不可变 Message-ID 的状态追踪
        3. 渲染 System 与 User Prompts 开启全新上下文
        4. 进行 ReAct 多轮工具调用闭环与保活
        5. 严格按实际处置结果持久化已处理状态至 memory
        6. 若传入 tracker，则同步收集处置决策与报表数据
        """
        if tracker:
            tracker.register_batch_emails(batch_emails)

        # 挂载当前批次邮件字典列表至 ToolContext 供各工具即时访问与元数据提取
        context.current_emails = [e.to_dict() for e in batch_emails]
        memory = context.memory

        # 建立当前批次 UID -> Message-ID 与垃圾状态映射
        uid_to_msg_id: dict[int, str] = {e.uid: e.message_id for e in batch_emails if e.message_id}
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
                        + "\n请为这些邮件调用 `apply_labels` 明确处置去向。"
                        "若判断确认保留在当前目录随时查阅（无需增删标签），请调用 `apply_labels(email_uids=[...], add=[], remove=[], tldr='...')` 明确确认留存并记录备忘。"
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

                tool_result = execute_tool(fn_name, parsed_args, context)

                # 仅当 apply_labels 成功执行时，才确立邮件的最终去向并加入持久化集合
                if tool_result.get("status") == "success":
                    affected_uids = tool_result.get("affected_uids", [])
                    if fn_name == "apply_labels":
                        adds = parsed_args.get("add", [])
                        removes = parsed_args.get("remove", [])
                        tldr = parsed_args.get("tldr", "")
                        for u in affected_uids:
                            try:
                                u_int = int(u)
                                if u_int in uid_to_msg_id:
                                    m_id = uid_to_msg_id[u_int]
                                    dispositioned_msg_ids.add(m_id)
                                    # 动态追踪垃圾邮件研判决策
                                    if "spam" in adds:
                                        msg_id_spam_map[m_id] = True
                                    elif "spam" in removes and ("inbox" in adds or not adds):
                                        msg_id_spam_map[m_id] = False
                            except (ValueError, TypeError):
                                continue

                        if tracker:
                            valid_uids: list[int] = []
                            for u in affected_uids:
                                try:
                                    valid_uids.append(int(u))
                                except (ValueError, TypeError):
                                    pass
                            tracker.record_labels(
                                uids=valid_uids,
                                add=adds,
                                remove=removes,
                                tldr=tldr,
                                current_code=context.current_code,
                            )
                    elif fn_name == "create_calendar_event" and tracker:
                        if tool_result.get("schedule"):
                            tracker.record_schedule(tool_result["schedule"])
                    elif fn_name == "create_email_draft" and tracker:
                        if tool_result.get("draft"):
                            tracker.record_draft(tool_result["draft"])

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(tool_result, ensure_ascii=False),
                })

        # 批次提交持久化状态：
        # 严格基于 dispositioned_msg_ids（仅经 apply_labels 成功处置并确立去向的邮件）入库
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
