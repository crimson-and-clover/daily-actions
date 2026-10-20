"""
Inbox Agent 邮件智能分流与结构化解析模块
利用 DeepSeek 大模型对邮件进行分门别类与关键行动项提取
"""

import sys
from pathlib import Path

from openai import OpenAI

from inbox_agent.config import DEEPSEEK_MODEL, DEEPSEEK_TIMEOUT
from utils.json_parser import parse_json_safely
from utils.prompt_loader import render_prompt_template
from utils.timezone import get_bjt_date_str, get_bjt_weekday_str

PROMPTS_DIR = Path(__file__).resolve().parent / "templates" / "prompts"
MAX_CLASSIFY_RETRIES = 3


def build_system_prompt(current_date: str, current_weekday: str) -> str:
    return render_prompt_template(
        PROMPTS_DIR,
        "classify_system.j2",
        current_date=current_date,
        current_weekday=current_weekday,
    )


def classify_email(email_item: dict, api_key: str, my_email: str = "") -> dict:
    """
    调用 DeepSeek 大模型对单封邮件进行智能分类与信息抽取
    返回包含分类和结构化字段的字典
    """
    subject = email_item.get("subject", "无主题")
    from_addr = email_item.get("from", "未知发件人")
    date_str = email_item.get("date", "")
    snippet = email_item.get("snippet", "")

    # 1. 硬编码规则：来自自己(me)或项目内部各CI任务通知邮件，直接放入系统通知分类
    my_email_lower = (my_email or "").strip().lower()
    from_addr_lower = from_addr.lower()
    subject_lower = subject.lower()

    # 判定是否为本人或系统自发通知
    is_from_me = False
    if my_email_lower and (my_email_lower in from_addr_lower):
        is_from_me = True
    elif any(sender_sig in from_addr_lower for sender_sig in ["daily actions", "@github.com", "notifications@github.com"]):
        is_from_me = True

    # 判定是否属于内部已知任务前缀
    is_internal_ci = any(ci_tag in subject_lower for ci_tag in ["[paper agent]", "[world news]", "[market fx]", "[inbox agent]", "daily actions"])

    if is_from_me or is_internal_ci:
        return {
            "category": "newsletter_system",
            "priority": "P2",
            "tldr": subject[:30],
            "action_items": [],
            "event_time": "",
            "event_date": "",
            "reason": "系统内建CI报告白名单",
            "is_internal_ci": is_internal_ci or ("daily actions" in from_addr_lower),
        }

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
        timeout=DEEPSEEK_TIMEOUT,
        max_retries=2,
    )

    current_date = get_bjt_date_str()
    current_weekday = get_bjt_weekday_str()

    sys_prompt = build_system_prompt(current_date, current_weekday)
    user_prompt = render_prompt_template(
        PROMPTS_DIR,
        "classify_user.j2",
        current_date=current_date,
        current_weekday=current_weekday,
        from_addr=from_addr,
        date_str=date_str,
        subject=subject,
        snippet=snippet,
    )

    last_content = ""
    for attempt in range(1, MAX_CLASSIFY_RETRIES + 1):
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=20000,
        )
        content = resp.choices[0].message.content or ""
        last_content = content
        parsed = parse_json_safely(content, strict=False)

        if isinstance(parsed, dict) and "category" in parsed:
            cat = parsed.get("category")
            if cat in ["schedule", "important", "newsletter_system", "marketing", "spam"]:
                parsed["category"] = cat
                parsed["priority"] = parsed.get("priority", "P2")
                parsed["tldr"] = parsed.get("tldr", subject[:30]).replace("\n", " ").strip()
                parsed["action_items"] = parsed.get("action_items", [])
                parsed["event_time"] = parsed.get("event_time", "")
                parsed["event_date"] = parsed.get("event_date", "").strip()
                # 智能提取提前通知天数
                try:
                    adv = int(parsed.get("advance_days", 0))
                    parsed["advance_days"] = max(0, min(adv, 30))
                except Exception:
                    parsed["advance_days"] = 3 if cat == "schedule" else 0
                parsed["reason"] = parsed.get("reason", "")
                return parsed
            else:
                print(
                    f"[Classifier Warning] 第 {attempt}/{MAX_CLASSIFY_RETRIES} 次分类输出未知的类别 '{cat}'，准备重试...",
                    file=sys.stderr,
                )
        else:
            print(
                f"[Classifier Warning] 第 {attempt}/{MAX_CLASSIFY_RETRIES} 次未能解析为合法分类 JSON，准备重试... 原始内容: {content}",
                file=sys.stderr,
            )

    raise RuntimeError(f"[Classifier Fatal] 大模型返回内容重试 {MAX_CLASSIFY_RETRIES} 次后仍无法解析为合法分类 JSON: {last_content}")


def build_historical_system_prompt(current_date: str, current_weekday: str) -> str:
    return render_prompt_template(
        PROMPTS_DIR,
        "history_system.j2",
        current_date=current_date,
        current_weekday=current_weekday,
    )


def classify_history_email(email_item: dict, api_key: str, my_email: str = "") -> dict:
    """
    针对 90 天以上历史邮件的大模型决策：
    判断是否删除、是否归档至指定目录，或者因依然具备信息量/日程有效而保留在收件箱。
    """
    subject = email_item.get("subject", "无主题")
    from_addr = email_item.get("from", "未知发件人")
    date_str = email_item.get("date", "")
    snippet = email_item.get("snippet", "")

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
        timeout=DEEPSEEK_TIMEOUT,
        max_retries=2,
    )

    current_date = get_bjt_date_str()
    current_weekday = get_bjt_weekday_str()

    sys_prompt = build_historical_system_prompt(current_date, current_weekday)
    user_prompt = render_prompt_template(
        PROMPTS_DIR,
        "history_user.j2",
        current_date=current_date,
        current_weekday=current_weekday,
        from_addr=from_addr,
        date_str=date_str,
        subject=subject,
        snippet=snippet,
    )

    last_content = ""
    for attempt in range(1, MAX_CLASSIFY_RETRIES + 1):
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=20000,
        )
        content = resp.choices[0].message.content or ""
        last_content = content
        parsed = parse_json_safely(content, strict=False)

        if isinstance(parsed, dict) and "action" in parsed:
            act = parsed.get("action")
            if act in ["delete", "archive_notifications", "archive_promotions", "archive_general", "keep_inbox"]:
                parsed["action"] = act
                parsed["tldr"] = parsed.get("tldr", subject[:30]).replace("\n", " ").strip()
                parsed["action_items"] = parsed.get("action_items", [])
                parsed["event_date"] = (parsed.get("event_date") or "").strip()
                parsed["event_time"] = (parsed.get("event_time") or "").strip()
                try:
                    parsed["advance_days"] = max(0, min(int(parsed.get("advance_days", 0)), 30))
                except Exception:
                    parsed["advance_days"] = 0
                parsed["reason"] = parsed.get("reason", "")
                return parsed
            else:
                print(
                    f"[Classifier Warning] 第 {attempt}/{MAX_CLASSIFY_RETRIES} 次历史决策输出未知的动作 '{act}'，准备重试...",
                    file=sys.stderr,
                )
        else:
            print(
                f"[Classifier Warning] 第 {attempt}/{MAX_CLASSIFY_RETRIES} 次历史决策未能解析为合法 JSON，准备重试... 原始内容: {content}",
                file=sys.stderr,
            )

    raise RuntimeError(f"[Classifier Fatal] 大模型返回内容重试 {MAX_CLASSIFY_RETRIES} 次后仍无法解析为合法历史处置决策 JSON: {last_content}")
