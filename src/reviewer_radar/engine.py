"""
Reviewer Radar ReAct 多轮自主探索与工具调用引擎 (Engine)
驱动 Agent 在 CCF-DDL 日程导引下，自主调用工具对各大顶会官网、Workshops 与 OpenReview 进行深度巡查
"""

import json
from typing import Any

from openai import OpenAI

from reviewer_radar.config import DEEPSEEK_API_KEY, TEMPLATES_PROMPTS_DIR, USER_ACADEMIC_PROFILE
from reviewer_radar.tools import AGENT_TOOLS, ToolContext, execute_tool
from utils.prompt_loader import render_prompt_template
from utils.timezone import get_now_bjt


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
    )


def build_radar_user_prompt() -> str:
    """从 Jinja2 模板渲染初始 User Prompt"""
    return render_prompt_template(
        TEMPLATES_PROMPTS_DIR,
        "radar_user.j2",
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
        max_turns: int = 12,
    ) -> str:
        """运行自主 ReAct 探索工作流"""
        sys_prompt = build_radar_system_prompt()
        user_prompt = build_radar_user_prompt()

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
                )
            except Exception as e:
                print(f"[RadarEngine] 模型推理异常: {e}")
                break

            choice = resp.choices[0]
            msg = choice.message
            tool_calls = getattr(msg, "tool_calls", None)

            # 将 Assistant 的回答（含思考与 tool_calls）追加进会话历史
            messages.append(msg.model_dump())

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
                    "content": json.dumps(result, ensure_ascii=False),
                })

        return final_summary
