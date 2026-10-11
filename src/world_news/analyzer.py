"""
AI 多维度量化评估与市场传导研判模块 (DeepSeek Multi-Turn Intelligence Analyzer)
支持多轮对话递进分析 (Turn 1: 初筛量化打分 -> Turn 2: 深度传导研判与报告合成)
内置网络波动指数退避重试 (Exponential Backoff Retries) 与结构校验
"""

import sys
import time
from pathlib import Path

from openai import OpenAI

from utils.json_parser import parse_json_safely
from utils.prompt_loader import render_prompt_template
from world_news.config import (
    DEEPSEEK_MODEL,
    DEEPSEEK_TIMEOUT,
    DEFAULT_MAX_RETRIES,
    SCORE_THRESHOLD,
)

PROMPTS_DIR = Path(__file__).resolve().parent / "templates" / "prompts"


def _post_chat_completion(
    client: OpenAI,
    messages: list,
    model: str,
    stage_name: str,
) -> tuple[dict, str]:
    """
    通用单轮请求调用函数，基于官方 OpenAI SDK 发起结构化输出交互并进行 JSON 校验
    返回 (解析后的字典, 助手原始回答文本)
    """
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=20000,
        )
        raw_content = resp.choices[0].message.content or ""
        parsed = parse_json_safely(raw_content)
        if parsed:
            return parsed, raw_content
        print(f"  [{stage_name}] 响应解析失败: 返回文本无法解析为合法 JSON (长度: {len(raw_content)})", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"  [{stage_name}] 调用异常: {e}", file=sys.stderr, flush=True)

    return None, None


def build_turn1_prompt(macro_items: list, tech_items: list) -> str:
    """构建 Turn 1 Prompt：全量候选池多维量化打分、去噪与筛选"""
    return render_prompt_template(
        PROMPTS_DIR,
        "turn1_screening.j2",
        macro_items=macro_items,
        tech_items=tech_items,
        score_threshold=SCORE_THRESHOLD,
    )


def build_turn2_prompt() -> str:
    """构建 Turn 2 Prompt：基于 Turn 1 筛选结果，展开深度市场传导逻辑与态势研判"""
    return render_prompt_template(
        PROMPTS_DIR,
        "turn2_transmission.j2",
    )


def analyze_with_deepseek(
    macro_items: list,
    tech_items: list,
    api_key: str = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> dict:
    """
    通过 DeepSeek 开展多轮对话深度研判：
    - Turn 1: 跨源素材初步去噪与多维度量化评级打分 (带指数退避重试)
    - Turn 2: 针对精选标的展开深度市场定价传导逻辑与产业格局推演 (带重试与容错降级)
    """
    if not api_key:
        print("未检测到 DEEPSEEK_API_KEY，进入基础排版模式。")
        return None

    if not macro_items and not tech_items:
        print("[警告] 候选池素材为空，跳过 AI 分析。")
        return None

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
        timeout=float(DEEPSEEK_TIMEOUT),
        max_retries=max_retries,
    )
    t_start = time.time()

    print(f"正在启动 DeepSeek 多轮对话研判 (候选池: {len(macro_items)} 条宏观 + {len(tech_items)} 条科技)...")

    # ==========================
    # Turn 1: 初筛评分与去噪
    # ==========================
    turn1_prompt = build_turn1_prompt(macro_items, tech_items)
    messages = [
        {
            "role": "system",
            "content": ("You are a senior macro hedge fund strategist and systems architect. You strictly evaluate events and technologies across multi-dimensional criteria in valid JSON without emojis."),
        },
        {"role": "user", "content": turn1_prompt},
    ]

    print("[Turn 1] 执行多源素材初筛与多维度打分量化过滤...")
    turn1_data, turn1_raw = _post_chat_completion(
        client=client,
        messages=messages,
        model=DEEPSEEK_MODEL,
        stage_name="Turn 1 初筛打分",
    )

    if not turn1_data:
        print("[失败] Turn 1 初筛失败，无法进入深度传导研判。", file=sys.stderr)
        return None

    selected_events = turn1_data.get("selected_world_events") or turn1_data.get("world_events") or []
    selected_tech = turn1_data.get("selected_tech_trends") or turn1_data.get("tech_trends") or []
    print(f"[Turn 1 完成] 精选达标事件 {len(selected_events)} 条，硬核开源项目 {len(selected_tech)} 条")

    # ==========================
    # Turn 2: 深度传导与报告合成
    # ==========================
    messages.append({"role": "assistant", "content": turn1_raw})
    turn2_prompt = build_turn2_prompt()
    messages.append({"role": "user", "content": turn2_prompt})

    print("[Turn 2] 执行资产定价传导逻辑推演与综合内参合成...")
    turn2_data, _ = _post_chat_completion(
        client=client,
        messages=messages,
        model=DEEPSEEK_MODEL,
        stage_name="Turn 2 深度传导",
    )

    total_cost = time.time() - t_start

    if turn2_data and "world_events" in turn2_data and "tech_trends" in turn2_data:
        print(f"DeepSeek 多轮对话研判成功完成！(总耗时 {total_cost:.1f} 秒)")
        return turn2_data

    # Turn 2 降级保护：如果 Turn 2 响应结构不完整，但 Turn 1 成功，则安全组装基础回退
    if selected_events or selected_tech:
        print("[降级保护] Turn 2 结构不全，基于 Turn 1 筛选结果安全合并基础研报结构。")
        fallback_data = {
            "executive_summary": turn1_data.get("executive_summary", "全球宏观市场与计算技术动态综述"),
            "key_signals": turn1_data.get("key_signals", ["宏观利率", "地缘博弈", "开源基建", "技术突破"]),
            "world_events": selected_events,
            "tech_trends": selected_tech,
        }
        return fallback_data

    return None
