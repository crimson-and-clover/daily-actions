"""
Inbox Agent 邮件智能分流与结构化解析模块
利用 DeepSeek 大模型对邮件进行分门别类与关键行动项提取
"""

import sys
from email.utils import parseaddr
from pathlib import Path

from openai import OpenAI

from inbox_agent.config import DEEPSEEK_MODEL, DEEPSEEK_TIMEOUT
from inbox_agent.imap.models import Email
from inbox_agent.rules import is_internal_ci
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


def classify_email(email: Email, api_key: str, my_email: str = "") -> dict:
    """
    调用 DeepSeek 大模型对单封邮件进行智能分类与信息抽取
    返回包含分类和结构化字段的字典
    """
    subject = email.subject or "无主题"
    from_addr = email.from_addr or "未知发件人"
    date_str = email.date or ""
    snippet = email.snippet or ""

    # 1. 规则预判：判定是否为系统自身的自动化任务/CI报告
    if is_internal_ci(email.subject):
        return {
            "category": "newsletter_system",
            "priority": "P2",
            "tldr": subject[:30],
            "action_items": [],
            "event_time": "",
            "event_date": "",
            "reason": "系统内建CI报告规则白名单",
            "is_internal_ci": True,
        }

    # 提取真实发件人邮箱地址，杜绝显示名伪造 (如 "security@github.com" <evil@attacker.example>)
    sender_real_addr = parseaddr(from_addr)[1].lower()

    # 判定是否为本人自发邮件
    my_email_lower = (my_email or "").strip().lower()
    is_from_me = bool(my_email_lower and my_email_lower == sender_real_addr)

    if is_from_me:
        return {
            "category": "newsletter_system",
            "priority": "P2",
            "tldr": subject[:30],
            "action_items": [],
            "event_time": "",
            "event_date": "",
            "reason": "来自本人的自发/往来邮件",
            "is_internal_ci": False,
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
        try:
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
            parsed = parse_json_safely(content)

            if isinstance(parsed, dict) and "category" in parsed:
                cat = parsed.get("category")
                if cat in ["schedule", "important", "newsletter_system", "marketing", "spam"]:
                    parsed["category"] = cat
                    parsed["priority"] = parsed.get("priority", "P2")
                    tldr = parsed.get("tldr")
                    parsed["tldr"] = (tldr if isinstance(tldr, str) and tldr.strip() else subject[:30]).replace("\n", " ").strip()
                    action_items = parsed.get("action_items")
                    parsed["action_items"] = action_items if isinstance(action_items, list) else []
                    parsed["event_time"] = (parsed.get("event_time") or "").strip()
                    parsed["event_date"] = (parsed.get("event_date") or "").strip()
                    # 智能提取提前通知天数
                    try:
                        adv = int(parsed.get("advance_days", 0))
                        parsed["advance_days"] = max(0, min(adv, 30))
                    except Exception:
                        parsed["advance_days"] = 3 if cat == "schedule" else 0
                    parsed["reason"] = (parsed.get("reason") or "").strip()
                    return parsed
                else:
                    print(
                        f"[Classifier Warning] 第 {attempt}/{MAX_CLASSIFY_RETRIES} 次分类输出未知的类别 '{cat}'，准备重试...",
                        file=sys.stderr,
                    )
            else:
                print(
                    f"[Classifier Warning] 第 {attempt}/{MAX_CLASSIFY_RETRIES} 次未能解析为合法分类 JSON，准备重试... 原始内容: {content[:200]}",
                    file=sys.stderr,
                )
        except Exception as e:
            print(
                f"[Classifier Warning] 第 {attempt}/{MAX_CLASSIFY_RETRIES} 次调用或解析异常: {e}，准备重试...",
                file=sys.stderr,
            )

    raise RuntimeError(f"[Classifier Fatal] 大模型返回内容重试 {MAX_CLASSIFY_RETRIES} 次后仍无法解析为合法分类 JSON: {last_content[:200]}")


def build_historical_system_prompt(current_date: str, current_weekday: str) -> str:
    return render_prompt_template(
        PROMPTS_DIR,
        "history_system.j2",
        current_date=current_date,
        current_weekday=current_weekday,
    )


def classify_history_email(email: Email, api_key: str, my_email: str = "") -> dict:
    """
    针对 90 天以上历史邮件的大模型决策：
    判断是否删除、是否归档至指定目录，或者因依然具备信息量/日程有效而保留在收件箱。
    """
    subject = email.subject or "无主题"
    from_addr = email.from_addr or "未知发件人"
    date_str = email.date or ""
    snippet = email.snippet or ""

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
        try:
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
            parsed = parse_json_safely(content)

            if isinstance(parsed, dict) and "action" in parsed:
                act = parsed.get("action")
                if act in ["delete", "archive_notifications", "archive_promotions", "archive_general", "keep_inbox"]:
                    parsed["action"] = act
                    tldr = parsed.get("tldr")
                    parsed["tldr"] = (tldr if isinstance(tldr, str) and tldr.strip() else subject[:30]).replace("\n", " ").strip()
                    action_items = parsed.get("action_items")
                    parsed["action_items"] = action_items if isinstance(action_items, list) else []
                    parsed["event_date"] = (parsed.get("event_date") or "").strip()
                    parsed["event_time"] = (parsed.get("event_time") or "").strip()
                    try:
                        parsed["advance_days"] = max(0, min(int(parsed.get("advance_days", 0)), 30))
                    except Exception:
                        parsed["advance_days"] = 0
                    parsed["reason"] = (parsed.get("reason") or "").strip()
                    return parsed
                else:
                    print(
                        f"[Classifier Warning] 第 {attempt}/{MAX_CLASSIFY_RETRIES} 次历史决策输出未知的动作 '{act}'，准备重试...",
                        file=sys.stderr,
                    )
            else:
                print(
                    f"[Classifier Warning] 第 {attempt}/{MAX_CLASSIFY_RETRIES} 次历史决策未能解析为合法 JSON，准备重试... 原始内容: {content[:200]}",
                    file=sys.stderr,
                )
        except Exception as e:
            print(
                f"[Classifier Warning] 第 {attempt}/{MAX_CLASSIFY_RETRIES} 次历史决策调用或解析异常: {e}，准备重试...",
                file=sys.stderr,
            )

    raise RuntimeError(f"[Classifier Fatal] 大模型返回内容重试 {MAX_CLASSIFY_RETRIES} 次后仍无法解析为合法历史处置决策 JSON: {last_content[:200]}")
