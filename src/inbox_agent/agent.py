"""
Inbox Agent (智能邮件助手)
- 运行机制：
  1. 状态持久化 (InboxMemory)：记录已分类邮件 ID，防重防漏
  2. 邮箱交互 (GmailClient)：安全连接 IMAP 抓取收件箱近 2 天未处理邮件
  3. 智能认知分流 (DeepSeek Flash)：识别待办日程 (schedule)、重要联络 (important)、系统资讯 (newsletter_system)、营销推广 (spam_marketing)
  4. 深度托管安全执行：
     - 将垃圾推广邮件安全搬移至 [Gmail]/Spam（绝不直接删除当前邮件）
     - 自动检测并清理垃圾箱/废件箱中滞留 90 天以上的过期垃圾邮件
  5. 报告渲染与多渠道分发：
     - 生成干练无 Emoji 邮件简报并分发
     - 归档生成 GitHub Pages 静态收件箱专区报告
"""

import sys
from datetime import datetime
from pathlib import Path

from inbox_agent.classifier import classify_email
from inbox_agent.config import (
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
from inbox_agent.imap_client import GmailClient, mutf7_decode
from inbox_agent.memory import InboxMemory
from inbox_agent.renderer import render_email_report
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
        print(f"[IMAP Warning] 获取垃圾箱邮件异常: {e}", file=sys.stderr)

    # 1. 过滤已处理收件箱邮件
    unprocessed_emails = [e for e in raw_emails if not memory.is_processed(e.get("message_id"))]
    print(f"[过滤] 待分类新邮件: {len(unprocessed_emails)} 封 (已跳过历史处理邮件 {len(raw_emails) - len(unprocessed_emails)} 封)")

    # 预先获取并缓存目标文件夹，避免频繁请求
    promotions_folder = client.get_promotions_folder_name()
    notifications_folder = client.get_notifications_folder_name()

    schedules = []
    importants = []
    systems = []
    marketings = []
    spams = []
    marketings_moved_count = 0
    systems_moved_count = 0
    spams_moved_count = 0

    # 分批执行收件箱新邮件研判与分流 (每批 10 封，边研判边执行并即时持久化)
    BATCH_SIZE = 10
    total_unprocessed = len(unprocessed_emails)
    total_batches = (total_unprocessed + BATCH_SIZE - 1) // BATCH_SIZE if total_unprocessed > 0 else 0

    for batch_idx in range(0, total_unprocessed, BATCH_SIZE):
        batch = unprocessed_emails[batch_idx : batch_idx + BATCH_SIZE]
        batch_num = (batch_idx // BATCH_SIZE) + 1
        print(f"\n--- [批次 {batch_num}/{total_batches}] 正在研判 {len(batch)} 封收件箱新邮件 ---")

        batch_marketings_uids = []
        batch_systems_uids = []
        batch_spams_uids = []

        for item in batch:
            if client.imap:
                client.noop()

            c_res = classify_email(item, DEEPSEEK_API_KEY, my_email=GMAIL_USER)
            merged = {**item, **c_res}
            cat = c_res.get("category", "newsletter_system")
            uid = item.get("uid")
            m_id = item.get("message_id")

            if cat == "schedule":
                # 有日程待办：严格留在 INBOX，不加入任何移动列表
                schedules.append(merged)
                if merged.get("event_date"):
                    memory.add_schedule(merged)
                memory.mark_processed(m_id, is_spam=False)
            elif cat == "important":
                # 重要来信与政务通知：严格留在 INBOX，不加入任何移动列表
                importants.append(merged)
                memory.mark_processed(m_id, is_spam=False)
            elif cat == "marketing":
                # 商业营销：安全归档至商业推广
                marketings.append(merged)
                if uid:
                    batch_marketings_uids.append(uid)
                memory.mark_processed(m_id, is_spam=False)
            elif cat == "spam":
                # 垃圾欺诈：移至垃圾邮件
                spams.append(merged)
                if uid:
                    batch_spams_uids.append(uid)
                memory.mark_processed(m_id, is_spam=True)
            elif cat == "newsletter_system":
                # 纯系统服务通知/订阅资讯：归档至系统通知目录
                # 若为当前项目自发 CI 任务邮件，直接在简报展示层过滤掉，不冗余呈现
                if not merged.get("is_internal_ci"):
                    systems.append(merged)
                if uid:
                    batch_systems_uids.append(uid)
                memory.mark_processed(m_id, is_spam=False)
            else:
                # 任何其它未知或不确定的邮件：一律安全留在 INBOX，绝不擅自移动！
                importants.append(merged)
                memory.mark_processed(m_id, is_spam=False)

        # 本批次即时执行 IMAP 移动
        if client.imap:
            if batch_marketings_uids:
                b_m = client.archive_emails(batch_marketings_uids, folder_name=promotions_folder)
                marketings_moved_count += b_m
            if batch_systems_uids:
                b_s = client.archive_emails(batch_systems_uids, folder_name=notifications_folder)
                systems_moved_count += b_s
            if batch_spams_uids:
                b_sp = client.move_to_spam(batch_spams_uids)
                spams_moved_count += b_sp

        # 本批次即时保存记忆库，防止网络偶发异常或中断丢失成果
        memory.save()
        print(f"  [批次 {batch_num}/{total_batches} 落地完毕] 已累计移动: 商业推广 {marketings_moved_count} | 系统通知 {systems_moved_count} | 垃圾箱 {spams_moved_count}")

    # 2. 深度托管动作：复核 Google 拦截到 Spam 的邮件，排查误杀并作为正常邮件处理
    unprocessed_spams = [e for e in raw_spam_emails if not memory.is_processed(e.get("message_id"))]
    if unprocessed_spams:
        print(f"\n[垃圾箱复核] 正在对 Google 拦截的 {len(unprocessed_spams)} 封垃圾邮件进行排查...")
        for item in unprocessed_spams:
            if client.imap:
                client.noop()
            c_res = classify_email(item, DEEPSEEK_API_KEY, my_email=GMAIL_USER)
            cat = c_res.get("category", "spam")
            merged = {**item, **c_res}
            if cat != "spam":
                # 判定为非垃圾邮件 -> 属于 Google 误杀，直接放回对应目录并按正常邮件处理
                if cat == "marketing":
                    target_dest = promotions_folder
                elif cat == "newsletter_system":
                    target_dest = notifications_folder
                else:
                    target_dest = "INBOX"
                display_dest = mutf7_decode(target_dest)
                print(f"[误杀处理] 发现被误判邮件: '{item.get('subject')}' (归属: {cat})，放回 {display_dest} 并按常规邮件处理...")
                if client.imap:
                    client.rescue_from_spam(item.get("uid"), target_folder=target_dest)

                # 直接按常规邮件分流到对应分类
                if cat == "schedule":
                    schedules.append(merged)
                    if merged.get("event_date"):
                        memory.add_schedule(merged)
                elif cat == "important":
                    importants.append(merged)
                elif cat == "marketing":
                    marketings.append(merged)
                else:
                    systems.append(merged)
                memory.mark_processed(item.get("message_id"), is_spam=False)
            else:
                # 确认确实是垃圾邮件，保持留在 Spam 中
                memory.mark_processed(item.get("message_id"), is_spam=True)

        memory.save()

    if client.imap:
        client.close()

    # 组织报告时间与插槽
    date_str = now_dt.strftime("%Y-%m-%d")
    run_slot = get_run_slot_name(now_dt)

    # 日程池唤醒：根据 AI 决定的提前天数及到期情况提取待办 (Today's Agenda & Pre-Alerts)
    today_due_schedules = memory.get_due_schedules(today_str=date_str)
    # 清理过期超过3天的日程
    memory.prune_expired_schedules(today_str=date_str)

    # 生成邮件 HTML (严格只发邮件，不生成亦不归档任何静态网页)
    email_html = render_email_report(
        date_str=now_dt.strftime("%Y-%m-%d %H:%M"),
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
    )

    # 邮件发送：遵循无 Emoji、干练高信息密度规则
    due_today_tag = f" | 今日到期{len(today_due_schedules)}项" if today_due_schedules else ""
    subject = f"[Inbox Agent] {date_str} 收件箱简报[{run_slot}]: {len(schedules)}项新增待办{due_today_tag} | {len(importants)}封重要 | 归档{systems_moved_count}封通知 | 隔离{marketings_moved_count}封营销 | 移入{spams_moved_count}封垃圾"
    preview_email_path = Path(__file__).resolve().parent / "preview_email.html"

    # 发送通知邮件并确保状态持久化
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
        print("=== [Inbox Agent] 状态已保存，执行完毕 ===")


if __name__ == "__main__":
    main()
