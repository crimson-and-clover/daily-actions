"""
大模型 JSON 输出防御性安全解析模块 (Safe LLM JSON Parser)
基于 json-repair 实现对 Markdown 剥壳、尾随逗号、未转义字符及截断补全的安全容错解析
"""

import json_repair


def parse_json_safely(raw_text: str, strict: bool = False) -> dict | list | None:
    """
    从大模型原始回复中安全提取并解析合法 JSON：
    1. 借助 json-repair 自动剥离 Markdown 代码块标记 (```json ... ```) 与前后自然语言冗余；
    2. 自动修复尾随逗号 (trailing commas) 且绝不损坏正文字符串；
    3. 自动容错未转义换行符、控制字符与未闭合截断；
    4. 若无法解析为合法 dict 或 list，返回 None 杜绝异常崩溃。
    """
    if not raw_text or not isinstance(raw_text, str):
        return None

    raw_text = raw_text.strip()
    if not raw_text:
        return None

    try:
        res = json_repair.loads(raw_text)
        return res if isinstance(res, (dict, list)) else None
    except Exception:
        return None
