"""
大模型 JSON 输出防御性安全解析模块 (Safe LLM JSON Parser)
基于 json-repair 实现对 Markdown 剥壳、尾随逗号、未转义字符及截断补全的安全容错解析
"""

import json_repair


def parse_json_safely(raw_text: str) -> dict | list | None:
    """
    从大模型原始回复中安全提取并解析合法 JSON：
    1. 借助 json-repair 自动剥离 Markdown 代码块标记 (```json ... ```) 与前后自然语言冗余；
    2. 自动修复尾随逗号 (trailing commas) 且绝不损坏正文字符串；
    3. 自动容错未转义换行符、控制字符与未闭合截断；
    4. 加入结构守卫，杜绝把自然语言中的中括号词条 (如 '[tech]') 误修成列表；
    5. 若无法解析为合法 dict 或 list，返回 None 杜绝异常崩溃。
    """
    if not raw_text or not isinstance(raw_text, str):
        return None

    clean = raw_text.strip()
    if not clean:
        return None

    # 若外层被 Markdown 代码块包裹，先取出内部核心内容
    if clean.startswith("```"):
        lines = clean.splitlines()
        if len(lines) >= 2 and lines[-1].strip().startswith("```"):
            clean = "\n".join(lines[1:-1]).strip()

    try:
        res = json_repair.loads(clean)
        if isinstance(res, dict):
            return res
        # 仅当正文真正以 '[' 开头时，才认可其为合法 JSON 数组
        # 彻底杜绝自由文本中散落的 "... [world news] ..." 被误修成列表
        if isinstance(res, list) and clean.startswith("["):
            return res
        return None
    except Exception:
        return None
