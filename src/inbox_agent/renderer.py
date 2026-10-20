"""
Inbox Agent 报告渲染模块
负责生成邮件 HTML 和 GitHub Pages 归档网页
"""

from inbox_agent.config import TEMPLATES_HTML_DIR
from utils.prompt_loader import render_html_template


def render_email_report(
    date_str: str,
    run_slot: str,
    schedules: list,
    today_due_schedules: list,
    importants: list,
    systems: list,
    marketings: list,
    spams: list,
    marketings_moved_count: int,
    systems_moved_count: int = 0,
    spams_moved_count: int = 0,
    pruned_count: int = 0,
    rescued_items: list = None,
) -> str:
    """渲染邮件 HTML (仅用于个人通知邮件发送，绝不在任何公开网页归档，开启 autoescape 防止 HTML 注入)"""
    return render_html_template(
        TEMPLATES_HTML_DIR,
        "email.html",
        date_str=date_str,
        run_slot=run_slot,
        schedules=schedules,
        today_due_schedules=today_due_schedules,
        importants=importants,
        systems=systems,
        marketings=marketings,
        spams=spams,
        marketings_moved_count=marketings_moved_count,
        systems_moved_count=systems_moved_count,
        spams_moved_count=spams_moved_count,
        pruned_count=pruned_count,
        rescued_items=rescued_items or [],
    )


def render_history_email_report(
    date_str: str,
    processed_count: int,
    deleted_count: int,
    notif_archived_count: int,
    promo_archived_count: int,
    gen_archived_count: int,
    kept_items: list,
    total_history_cleaned: int = 0,
) -> str:
    """渲染历史邮件整理汇报 HTML (使用独立 history.html 模板)"""
    return render_html_template(
        TEMPLATES_HTML_DIR,
        "history.html",
        date_str=date_str,
        processed_count=processed_count,
        deleted_count=deleted_count,
        notif_archived_count=notif_archived_count,
        promo_archived_count=promo_archived_count,
        gen_archived_count=gen_archived_count,
        kept_items=kept_items or [],
        total_history_cleaned=total_history_cleaned,
    )
