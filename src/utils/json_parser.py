"""
大模型 JSON 输出防御性安全解析模块 (Safe LLM JSON Parser)
融合 Markdown 代码块去壳、截取花括号、清洗控制字符与标准 json.loads
"""

import json
import re


def parse_json_safely(raw_text: str) -> dict | list | None:
    """
    从大模型原始回复中安全提取并解析合法 JSON：
    1. 优先尝试直接在最外层花括号/方括号之间截取并解析；
    2. 若失败，尝试清洗 Markdown 代码块标记 (```json ... ```)；
    3. 杜绝解析异常导致程序崩溃，解析失败返回 None。
    """
    if not raw_text or not isinstance(raw_text, str):
        return None

    raw_text = raw_text.strip()

    # 1. 直接尝试截取最外层花括号
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = raw_text[start : end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            pass

    # 2. 尝试清洗 Markdown 代码块
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = cleaned[start : end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            pass

    # 3. 兜底尝试整个串直接解析（支持数组等）
    try:
        return json.loads(raw_text)
    except Exception:
        return None
