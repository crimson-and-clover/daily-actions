"""
Reviewer Radar ReAct 多轮自主探索与工具调用引擎 (Engine)
驱动 Agent 在 CCF-DDL 日程导引下，自主调用工具对各大顶会官网、Workshops 与 OpenReview 进行深度巡查
"""

import json
import sys
from typing import Any

from openai import OpenAI
from pydantic import TypeAdapter

from reviewer_radar.ccf_timeline import fetch_conference_targets
from reviewer_radar.config import DEEPSEEK_API_KEY, TEMPLATES_PROMPTS_DIR, USER_ACADEMIC_PROFILE
from reviewer_radar.models import ConferencePhase, ConferenceTarget
from reviewer_radar.tools import AGENT_TOOLS, ToolContext, execute_tool
from utils.prompt_loader import render_prompt_template
from utils.timezone import get_now_bjt

_TOOL_JSON_ADAPTER = TypeAdapter(Any)


def build_radar_system_prompt() -> str:
    """从 Jinja2 模板渲染 ReAct 决策 System Prompt"""
    now_bjt = get_now_bjt()
    return render_prompt_template(
        TEMPLATES_PROMPTS_DIR,
        "radar_system.j2",
        current_date_bjt=now_bjt.strftime("%Y-%m-%d %H:%M:%S"),
        user_publications=USER_ACADEMIC_PROFILE["publications"],
        user_expertise=USER_ACADEMIC_PROFILE["expertise"],
        openreview_url=USER_ACADEMIC_PROFILE.get("openreview_url", ""),
        scholar_url=USER_ACADEMIC_PROFILE.get("scholar_url", ""),
    )


def build_radar_user_prompt(active_targets: list[ConferenceTarget] | None = None) -> str:
    """从 Jinja2 模板渲染初始 User Prompt，可直接附带预同步的顶会日程上下文"""
    return render_prompt_template(
        TEMPLATES_PROMPTS_DIR,
        "radar_user.j2",
        active_targets=active_targets or [],
    )


class ReviewerRadarEngine:
    """基于 ReAct 多轮工具调用的学术审稿雷达自治引擎"""

    def __init__(
        self,
        api_key: str = DEEPSEEK_API_KEY,
        model: str = "deepseek-chat",
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY 未配置，ReAct 自主智能体无法启动")
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.deepseek.com",
            timeout=self.timeout,
            max_retries=2,
        )

    def run_autonomous_radar(
        self,
        context: ToolContext,
        max_turns: int = 100,
    ) -> str:
        """运行自主 ReAct 探索工作流"""
        # 1. 对话启动前预先拉取并解析顶会日程，固化到上下文缓存，避免空耗第一轮 LLM 工具调用
        if context.conference_cache is None and not context.fetch_error:
            try:
                context.conference_cache = fetch_conference_targets()
            except Exception as e:
                err_msg = f"拉取/解析顶会日程失败: {e}"
                print(f"[ReviewerRadar] {err_msg}", file=sys.stderr)
                context.fetch_error = err_msg
                return f"❌ 任务前置失败: {err_msg}"

        active_confs: list[ConferenceTarget] = []
        if context.conference_cache:
            active_confs = [
                t
                for t in context.conference_cache
                if (
                    t.phase in (ConferencePhase.ACTIVE_REVIEW, ConferencePhase.REBUTTAL_DECISION)
                    or (t.phase == ConferencePhase.PRE_DEADLINE and t.diff_days >= -45)
                )
                and t.diff_days <= 120
            ]
            active_confs.sort(key=lambda x: x.diff_days)

        sys_prompt = build_radar_system_prompt()
        user_prompt = build_radar_user_prompt(active_targets=active_confs)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ]

        turn = 0
        final_summary = ""

        while turn < max_turns:
            turn += 1
            print(f"[RadarEngine] ReAct 决策轮次 [{turn}/{max_turns}]...")

            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=AGENT_TOOLS,
                    tool_choice="auto",
                    max_tokens=20000,
                )
            except Exception as e:
                print(f"[RadarEngine] 模型推理异常: {e}", file=sys.stderr)
                context.fetch_error = context.fetch_error or f"模型推理异常: {e}"
                break

            choice = resp.choices[0]
            msg = choice.message
            tool_calls = getattr(msg, "tool_calls", None)

            # 规范构造最小 assistant 消息历史，杜绝透传第三方网关不兼容字段
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            if msg.content:
                assistant_msg["content"] = msg.content
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

            if not tool_calls:
                final_summary = msg.content or "已完成本轮顶会审稿巡检。"
                print(f"[RadarEngine] Agent 主动收敛，巡检汇报:\n{final_summary[:300]}...")
                break

            # 遍历并执行本次 Assistant 发起的所有 Tool Calls
            for tc in tool_calls:
                fn_name = tc.function.name
                call_id = tc.id
                raw_args = tc.function.arguments

                try:
                    parsed_args = json.loads(raw_args)
                except Exception:
                    parsed_args = {}

                print(f"[RadarEngine] 调用工具: `{fn_name}` -> {json.dumps(parsed_args, ensure_ascii=False)[:120]}")
                result = execute_tool(fn_name, parsed_args, context)

                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": _TOOL_JSON_ADAPTER.dump_json(result).decode("utf-8"),
                })

        return final_summary
