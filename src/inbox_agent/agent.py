"""
Inbox Agent (智能邮件助手) - Agentic ReAct 架构
- 运行机制：
  1. 状态持久化 (InboxMemory)：AES 加密保存已分类邮件 ID、日程待办与用户偏好规则
  2. 邮箱交互 (GmailClient)：安全连接 IMAP 抓取收件箱与垃圾箱待处理邮件
  3. 批次化决策驱动 (Batch ReAct)：
     - 严格以 10 封为一组 (BATCH_SIZE = 10) 开启全新独立会话上下文
     - 每次清空历史无包袱，重新注入 System Prompt 与【最新用户偏好规则库】
     - Agent 拥有完整工具箱，自主调用 move_emails, read_email_content, create_calendar_event, create_draft, save_user_preference 等
  4. 垃圾箱托管复核：
     - 以 10 封为一组循环复核 Google 拦截的垃圾邮件，AI 研判误判时调用 rescue_from_spam 安全解救
  5. 报告渲染与多渠道分发：
     - 汇总各批次成果，生成干练邮件简报并分发
"""

import sys
from datetime import datetime
from pathlib import Path

from inbox_agent.config import (
    BATCH_SIZE,
    DEEPSEEK_API_KEY,
    FETCH_DAYS_LIMIT,
    GMAIL_APP_PASS,
    GMAIL_USER,
    IS_CI,
    MAX_EMAILS_PER_RUN,
    NOTIFICATION_EMAIL,
    get_now_bjt,
    validate_config,
)
from inbox_agent.engine import AgentEngine
from inbox_agent.imap_client import GmailClient
from inbox_agent.memory import InboxMemory
from inbox_agent.renderer import render_email_report
from inbox_agent.tools import BatchTracker, ToolContext
from utils.mailer import send_email_html


def get_run_slot_name(now_dt: datetime) -> str:
    """根据运行时间生成时间段标签，如 晨间 / 午间 / 晚间"""
    hour = now_dt.hour
    if 5 <= hour < 11:
        return "晨间"
    elif 11 <= hour < 16:
        return "午间"
    elif 16 <= hour < 23:
        return "晚间"
    return "夜间"


def main():
    """日常收件箱巡检与分流主工作流 (适用于 GitHub Actions CI)"""
    validate_config(require_deepseek=True)
    now_dt = get_now_bjt()
    print(f"=== [Inbox Agent] 智能邮件助手启动 ({now_dt.strftime('%Y-%m-%d %H:%M:%S')} BJT) ===")

    memory = InboxMemory()
    client = GmailClient(username=GMAIL_USER, password=GMAIL_APP_PASS)

    print("[IMAP] 正在连接 Gmail 检查收件箱与垃圾箱...")
    if not client.connect():
        print("[IMAP Fatal Error] Gmail 登录/鉴权失败，请检查 GMAIL_USER 与 GMAIL_APP_PASS 凭据", file=sys.stderr)
        sys.exit(1)

    try:
        raw_emails = client.fetch_recent_emails(
            days=FETCH_DAYS_LIMIT,
            max_count=MAX_EMAILS_PER_RUN,
            is_processed_func=memory.is_processed,
        )
        print(f"[IMAP] 获取到收件箱近期邮件: {len(raw_emails)} 封")
    except Exception as e:
        print(f"[IMAP Fatal Error] 获取收件箱邮件异常: {e}", file=sys.stderr)
        client.close()
        sys.exit(1)

    try:
        raw_spam_emails = client.fetch_recent_spam_emails(days=FETCH_DAYS_LIMIT, max_count=30)
        print(f"[IMAP] 获取到垃圾箱近期待复核邮件: {len(raw_spam_emails)} 封")
    except Exception as e:
        print(f"[IMAP Fatal Error] 获取垃圾箱邮件异常: {e}", file=sys.stderr)
        client.close()
        sys.exit(1)

    # 1. 过滤已处理收件箱邮件
    unprocessed_emails = [e for e in raw_emails if not memory.is_processed(e.get("message_id"))]
    print(f"[过滤] 待分类新邮件: {len(unprocessed_emails)} 封 (已跳过历史处理邮件 {len(raw_emails) - len(unprocessed_emails)} 封)")

    tracker = BatchTracker()
    context = ToolContext(client=client, memory=memory, tracker=tracker)
    engine = AgentEngine(api_key=DEEPSEEK_API_KEY)

    total_unprocessed = len(unprocessed_emails)
    total_batches = (total_unprocessed + BATCH_SIZE - 1) // BATCH_SIZE if total_unprocessed > 0 else 0

    # 2. 分批执行收件箱新邮件研判与分流 (每批 10 封，全新对话上下文 + 携带全局偏好)
    for batch_idx in range(0, total_unprocessed, BATCH_SIZE):
        batch = unprocessed_emails[batch_idx : batch_idx + BATCH_SIZE]
        batch_num = (batch_idx // BATCH_SIZE) + 1
        print(f"\n--- [批次 {batch_num}/{total_batches}] 正在由 Agent 处理 {len(batch)} 封收件箱新邮件 ---")

        summary = engine.run_batch_triage(
            batch_emails=batch,
            batch_num=batch_num,
            total_batches=total_batches,
            context=context,
            user_email=GMAIL_USER,
        )
        print(f"  [批次 {batch_num}/{total_batches} 总结]: {summary}")

        # 本批次即时保存记忆库，防止网络偶发中断丢失进度
        memory.save()
        print(f"  [批次进度已保存] 累计移动: 商业推广 {tracker.marketings_moved_count} | 系统通知 {tracker.systems_moved_count} | 垃圾箱 {tracker.spams_moved_count}")

    # 3. 垃圾箱误杀复核托管：同样严格以 10 封为一组循环交由 Agent 复核并解救误杀
    unprocessed_spams = [e for e in raw_spam_emails if not memory.is_processed(e.get("message_id"))]
    if unprocessed_spams:
        total_unprocessed_spams = len(unprocessed_spams)
        total_spam_batches = (total_unprocessed_spams + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"\n[垃圾箱复核] 开始分批复核 {total_unprocessed_spams} 封垃圾箱拦截邮件 (共 {total_spam_batches} 批)...")

        for s_idx in range(0, total_unprocessed_spams, BATCH_SIZE):
            s_batch = unprocessed_spams[s_idx : s_idx + BATCH_SIZE]
            s_batch_num = (s_idx // BATCH_SIZE) + 1
            print(f"\n--- [垃圾箱复核批次 {s_batch_num}/{total_spam_batches}] 正在由 Agent 复核 {len(s_batch)} 封拦截邮件 ---")

            s_summary = engine.run_batch_triage(
                batch_emails=s_batch,
                batch_num=s_batch_num,
                total_batches=total_spam_batches,
                context=context,
                user_email=GMAIL_USER,
            )
            print(f"  [垃圾箱复核批次 {s_batch_num}/{total_spam_batches} 总结]: {s_summary}")

            # 将本批确认未解救的垃圾标记为 processed(is_spam=True)
            for item in s_batch:
                m_id = item.get("message_id")
                uid = str(item.get("uid", ""))
                is_rescued = any(r.get("uid") == uid for r in tracker.rescued_items)
                if not is_rescued:
                    memory.mark_processed(m_id, is_spam=True)
            memory.save()

    if client.imap:
        client.close()

    # 4. 组织报告时间与插槽
    date_str = now_dt.strftime("%Y-%m-%d")
    run_slot = get_run_slot_name(now_dt)

    # 日程池唤醒：根据 AI 决定的提前天数及到期情况提取待办 (Today's Agenda & Pre-Alerts)
    today_due_schedules = memory.get_due_schedules(today_str=date_str)
    # 清理过期超过 3 天的历史日程
    memory.prune_expired_schedules(today_str=date_str)

    # 汇总所有重要留存类别（包括普通重要、政务公函、银行证券、验证码）用于报告呈现
    all_importants = (
        tracker.importants
        + tracker.government_affairs
        + tracker.finance_bankings
        + tracker.verification_codes
    )

    # 5. 渲染邮件 HTML (严格只发邮件，不归档公开网页)
    email_html = render_email_report(
        date_str=now_dt.strftime("%Y-%m-%d %H:%M"),
        run_slot=run_slot,
        schedules=tracker.schedules,
        today_due_schedules=today_due_schedules,
        importants=all_importants,
        systems=tracker.systems,
        marketings=tracker.marketings,
        spams=tracker.spams,
        marketings_moved_count=tracker.marketings_moved_count,
        systems_moved_count=tracker.systems_moved_count,
        spams_moved_count=tracker.spams_moved_count,
        rescued_items=tracker.rescued_items,
    )

    # 6. 邮件发送：遵循干练高信息密度规则
    due_today_tag = f" | 今日到期{len(today_due_schedules)}项" if today_due_schedules else ""
    subject = (
        f"[Inbox Agent] {date_str} 收件箱简报[{run_slot}]: "
        f"{len(tracker.schedules)}项新增待办{due_today_tag} | "
        f"{len(all_importants)}封重要 | "
        f"归档{tracker.systems_moved_count}封通知 | "
        f"隔离{tracker.marketings_moved_count}封营销 | "
        f"移入{tracker.spams_moved_count}封垃圾"
    )
    preview_email_path = Path(__file__).resolve().parent / "preview_email.html"

    try:
        send_email_html(
            subject=subject,
            html_content=email_html,
            gmail_user=GMAIL_USER,
            gmail_pass=GMAIL_APP_PASS,
            receiver=NOTIFICATION_EMAIL,
            is_ci=IS_CI,
            preview_path=preview_email_path,
        )
    finally:
        memory.save()
        print("=== [Inbox Agent] 状态已加密保存，执行完毕 ===")


if __name__ == "__main__":
    main()
