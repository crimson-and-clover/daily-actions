"""
Reviewer Radar Agent 总调度与执行入口
基于 ReAct 自主探索引擎与 CCF-DDL 顶会日程驱动，为用户全自动捕获高价值审稿机会
"""

import sys
from pathlib import Path

from reviewer_radar.config import (
    GMAIL_APP_PASS,
    GMAIL_USER,
    IS_CI,
    NOTIFICATION_EMAIL,
    validate_config,
)
from reviewer_radar.engine import ReviewerRadarEngine
from reviewer_radar.memory import RadarMemory
from reviewer_radar.renderer import render_reviewer_email
from reviewer_radar.tools import ToolContext
from utils.mailer import send_email_html
from utils.timezone import get_now_bjt


def run_reviewer_radar() -> None:
    """执行审稿雷达 ReAct 自主巡检主任务"""
    now_bjt = get_now_bjt()
    now_bjt_str = now_bjt.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[ReviewerRadar] 启动审稿人招募巡检 (基准时间: {now_bjt_str})...")

    validate_config()
    memory = RadarMemory()
    context = ToolContext(memory=memory)

    # 1. 唤起 ReAct 智能体多轮自主探索决策 (充分穷尽排查，上限 100 轮)
    engine = ReviewerRadarEngine()
    summary = engine.run_autonomous_radar(context=context, max_turns=100)
    if summary:
        print(f"[ReviewerRadar] 智能体巡检摘要:\n{summary}")

    recorded_opps = context.recorded_opportunities
    print(f"[ReviewerRadar] 巡检收敛，共捕获 {len(recorded_opps)} 个有效审稿入口")

    if not recorded_opps:
        if context.fetch_error:
            print(f"[ReviewerRadar Fatal] 巡检流程异常终止: {context.fetch_error}", file=sys.stderr)
            sys.exit(1)
        print("[ReviewerRadar] 本次未发现新的审稿招募或救火机会，流程结束。")
        memory.save(run_timestamp=now_bjt_str)
        return

    # 2. 渲染高信息密度 HTML 邮件
    email_html = render_reviewer_email(
        opportunities=recorded_opps,
        run_time_bjt=now_bjt_str,
    )
    email_subject = f"[Reviewer Radar] 发现 {len(recorded_opps)} 项顶会/Workshop 审稿机会"

    preview_path = Path(__file__).resolve().parent / "preview_email.html"

    # 3. 分发邮件简报
    print("[ReviewerRadar] 正在发送通知邮件...")
    send_email_html(
        subject=email_subject,
        html_content=email_html,
        gmail_user=GMAIL_USER,
        gmail_pass=GMAIL_APP_PASS,
        receiver=NOTIFICATION_EMAIL,
        is_ci=IS_CI,
        preview_path=preview_path,
    )

    # 4. 持久化保存记忆状态
    memory.save(run_timestamp=now_bjt_str)
    print("[ReviewerRadar] 巡检、推送与状态归档完成。")


if __name__ == "__main__":
    run_reviewer_radar()
