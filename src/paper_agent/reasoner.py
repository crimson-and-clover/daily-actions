"""
DeepSeek 大模型多轮技术解析与评分模块 (基于官方 OpenAI SDK 与 tenacity 重试)
"""

import sys
import time
from pathlib import Path

from openai import OpenAI

from utils.json_parser import parse_json_safely
from utils.prompt_loader import render_prompt_template

PROMPTS_DIR = Path(__file__).resolve().parent / "templates" / "prompts"


def quick_screen_abstract(paper: dict, api_key: str, track: dict = None) -> tuple[float, str]:
    """
    轻量快速初筛：仅基于 Title、Authors、Abstract 请求大模型给出相关性量化打分 (relevance) 与判定理由 (reason)。
    是否入选核心候选由外部 Python 业务代码根据 MIN_SCREEN_RELEVANCE_SCORE 自行判断。
    返回: (relevance_score: float, reason: str)
    """
    if not api_key:
        return 10.0, "未配置 API KEY，跳过初筛"

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=25.0, max_retries=2)

    track_tag = track.get("tag", "通用前沿AI算法") if track else "通用前沿AI算法"
    track_keywords = ", ".join(track.get("keywords", [])) if track else ""

    prompt = render_prompt_template(
        PROMPTS_DIR,
        "screen_abstract.j2",
        track_tag=track_tag,
        track_keywords=track_keywords,
        paper=paper,
    )

    try:
        resp = client.chat.completions.create(
            model="deepseek-flash",
            messages=[{"role": "system", "content": "You are a research screener returning strict JSON without emojis."}, {"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=20000,
        )
        raw_text = resp.choices[0].message.content or ""
        data = parse_json_safely(raw_text)
        if data and "relevance" in data:
            score = float(data["relevance"])
            reason = data.get("reason", "")
            return score, reason
    except Exception as e:
        print(f"     [初筛异常: {e}]，未能获取大模型初筛评分", file=sys.stderr, flush=True)
        return 0.0, f"初筛异常: {e}"


def reason_with_deepseek(paper: dict, api_key: str, track: dict = None) -> dict | None:
    """
    通过 DeepSeek 官方兼容 client 开展多轮对话：
    Turn 1: 全文核心提取 + 各维度量化打分（含赛道强相关性打分 relevance） + 白话输入输出定义
    Turn 2: 多轮精炼审校，压缩冗长叙述，校验 KaTeX 格式数学符号
    """
    if not api_key:
        print("  [警告] 未配置 DEEPSEEK_API_KEY，无法开展大模型精读。", file=sys.stderr, flush=True)
        return None

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=60.0, max_retries=2)

    full_info = paper.get("full_content", {})
    method_text = full_info.get("method", "") or paper["summary"]
    exp_text = full_info.get("experiments", "") or "请结合方法论与摘要评估基准表现"
    affiliations_text = full_info.get("affiliations", "") or paper.get("authors", "")

    model_name = "deepseek-flash"

    track_tag = track.get("tag", "通用前沿AI算法") if track else "通用前沿AI算法"
    track_keywords = ", ".join(track.get("keywords", [])) if track else ""

    # --- Turn 1: 首次技术解析与评分 ---
    turn1_prompt = render_prompt_template(
        PROMPTS_DIR,
        "deep_read_turn1.j2",
        track_tag=track_tag,
        track_keywords=track_keywords,
        paper=paper,
        affiliations_text=affiliations_text,
        method_text=method_text,
        exp_text=exp_text,
    )

    messages = [{"role": "system", "content": "You are a professional AI researcher providing technical paper analysis in strict JSON without any emojis."}, {"role": "user", "content": turn1_prompt}]

    t0 = time.time()
    try:
        resp1 = client.chat.completions.create(
            model=model_name,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=20000,
        )
        turn1_text = resp1.choices[0].message.content or ""
        turn1_result = parse_json_safely(turn1_text)
        if not turn1_result or "tldr" not in turn1_result or "scores" not in turn1_result:
            print(f"  [{model_name}] Turn 1 响应 JSON 结构不完整", file=sys.stderr, flush=True)
            return None
        messages.append({"role": "assistant", "content": turn1_text})
    except Exception as e:
        print(f"  [{model_name}] Turn 1 调用异常: {e}", file=sys.stderr, flush=True)
        return None

    # --- Turn 2: 多轮对话精炼审校 ---
    turn2_prompt = render_prompt_template(PROMPTS_DIR, "refine_turn2.j2")
    messages.append({"role": "user", "content": turn2_prompt})

    try:
        resp2 = client.chat.completions.create(
            model=model_name,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=20000,
        )
        turn2_text = resp2.choices[0].message.content or ""
        turn2_result = parse_json_safely(turn2_text)
        if turn2_result and "tldr" in turn2_result:
            cost = time.time() - t0
            print(f"     [{model_name}] 多轮审校完成 (耗时: {cost:.1f}s | 综合评分: {turn2_result.get('scores', {}).get('overall')}/10)", flush=True)
            return turn2_result
    except Exception as e:
        print(f"     [{model_name}] Turn 2 审校波动: {e}，优雅降级为初轮结果", file=sys.stderr, flush=True)

    cost = time.time() - t0
    print(f"     [{model_name}] 初轮解析完成 (审校跳过，耗时: {cost:.1f}s | 综合评分: {turn1_result.get('scores', {}).get('overall')}/10)", flush=True)
    return turn1_result
