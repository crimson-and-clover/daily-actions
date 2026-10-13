"""
Inbox History Agent (收件箱历史邮件归档与清理智能体)
专门针对 90 天以上的历史积压邮件：
1. 严格从最旧到较新 (旧 -> 新) 优先处理；
2. 单次 CI 最多处理 100 封，避免超时与 API 额度超限；
3. 交由 DeepSeek 智能决策：
   - 包含有效日程/高信息量/重要跟进事项 -> 保留 (keep_inbox) 并持久化待办
   - 有长期留存价值的凭证/账单/服务通知 -> 归档至'系统通知'目录
   - 商业营销/留存优惠 -> 归档至'商业推广'目录
   - 普通重要往来 -> 归档至'归档'目录
   - 过期无价值通知/推广/垃圾 -> 删除移入 [Gmail]/Trash 废纸篓
4. 与主 agent 共享状态，状态经过 Fernet AES 加密安全保存
"""

import sys
from pathlib import Path

from inbox_agent.classifier import classify_history_email
from inbox_agent.config import (
    DEEPSEEK_API_KEY,
    GMAIL_APP_PASS,
    GMAIL_USER,
    IS_CI,
    NOTIFICATION_EMAIL,
    PRUNE_DAYS,
    get_now_bjt,
    validate_config,
)
from inbox_agent.imap import GmailClient
from inbox_agent.memory import InboxMemory
from inbox_agent.renderer import render_history_email_report
from utils.mailer import send_email_html


def main():
    validate_config(require_deepseek=True)
    now_dt = get_now_bjt()
    print(f"=== [Inbox History Agent] 启动历史邮件清理与归档任务 ({now_dt.strftime('%Y-%m-%d %H:%M:%S')} BJT) ===")

    memory = InboxMemory()
    client = GmailClient(username=GMAIL_USER, password=GMAIL_APP_PASS)

    print(f"[IMAP] 正在连接 Gmail 检查早于 {PRUNE_DAYS} 天的历史邮件 (旧 -> 新)...")
    if not client.connect():
        print("[IMAP Fatal Error] Gmail 登录/鉴权失败，请检查凭据", file=sys.stderr)
        sys.exit(1)

    try:
        # 严格按最旧到较新抓取未处理历史邮件，最大 100 封
        raw_old_emails = client.fetch_old_emails(
            days=PRUNE_DAYS,
            max_count=100,
            is_processed_func=memory.is_history_processed,
        )
        print(f"[IMAP] 抓取到待研判历史邮件: {len(raw_old_emails)} 封")
    except Exception as e:
        print(f"[IMAP Fatal Error] 获取历史邮件异常: {e}", file=sys.stderr)
        client.close()
        sys.exit(1)

    if not raw_old_emails:
        print(f"[Inbox History Agent] 收件箱中没有超过 {PRUNE_DAYS} 天的未处理历史邮件，任务完成。")
        client.close()
        return

    # 分批执行配置 (每 10 封为一个 batch，边研判边执行并即时持久化)
    BATCH_SIZE = 10
    total_emails = len(raw_old_emails)
    total_batches = (total_emails + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"[AI 研判] 开始分批分析 {total_emails} 封收件箱历史邮件 (每批 {BATCH_SIZE} 封，共 {total_batches} 批，边研判边转移)...")

    # 预先获取并缓存目标文件夹，避免在批次循环中重复请求 folder list
    notif_folder = client.get_notifications_folder_name()
    promo_folder = client.get_promotions_folder_name()

    deleted_count = 0
    notif_archived_count = 0
    promo_archived_count = 0
    gen_archived_count = 0
    kept_items = []
    processed_count = 0

    for batch_idx in range(0, total_emails, BATCH_SIZE):
        batch = raw_old_emails[batch_idx : batch_idx + BATCH_SIZE]
        batch_num = (batch_idx // BATCH_SIZE) + 1
        print(f"\n--- [批次 {batch_num}/{total_batches}] 正在研判 {len(batch)} 封邮件 ---")

        batch_to_delete = []
        batch_to_notif = []
        batch_to_promo = []
        batch_to_archive = []

        for item in batch:
            # 心跳保活：防止 LLM 研判期间 IMAP 连接因闲置超时被断开
            if client.imap:
                client.noop()

            m_id = item.get("message_id")
            uid = item.get("uid")
            subject = item.get("subject", "无主题")

            decision = classify_history_email(item, DEEPSEEK_API_KEY, my_email=GMAIL_USER)
            action = decision.get("action", "delete")
            reason = decision.get("reason", "")
            tldr = decision.get("tldr", "")

            # 若发现依然包含有效的未来日程或关键跟进事项，写入待办池
            if decision.get("has_active_schedule") and decision.get("event_date"):
                merged_schedule = {**item, **decision}
                memory.add_schedule(merged_schedule)
                print(f"  [发现有效待办] '{subject}' -> 日期: {decision.get('event_date')} ({tldr})")

            if action == "delete":
                batch_to_delete.append(uid)
                print(f"  [决策: 移入废纸篓] '{subject}' (原因: {reason})")
            elif action == "archive_notifications":
                batch_to_notif.append(uid)
                print(f"  [决策: 归档系统通知] '{subject}' (原因: {reason})")
            elif action == "archive_promotions":
                batch_to_promo.append(uid)
                print(f"  [决策: 归档商业推广] '{subject}' (原因: {reason})")
            elif action == "archive_general":
                batch_to_archive.append(uid)
                print(f"  [决策: 通用归档] '{subject}' (原因: {reason})")
            elif action == "keep_inbox":
                kept_items.append({**item, **decision})
                print(f"  [决策: 保留收件箱] '{subject}' (原因: {reason})")

            # 标记已完成历史研判处理
            memory.mark_history_processed(m_id)
            processed_count += 1

        # 本批次研判完成，立即执行 IMAP 批量动作
        if client.imap:
            if batch_to_delete:
                b_del = client.move_to_trash(batch_to_delete)
                deleted_count += b_del
                memory.record_pruned(b_del)
            if batch_to_notif:
                notif_archived_count += client.archive_emails(batch_to_notif, folder_name=notif_folder)
            if batch_to_promo:
                promo_archived_count += client.archive_emails(batch_to_promo, folder_name=promo_folder)
            if batch_to_archive:
                gen_archived_count += client.archive_emails(batch_to_archive, folder_name="归档")

        # 核心：每完成一个批次立即持久化保存加密记忆库！
        # 即使后续网络异常或 CI 中途超时，前面已处理的批次也绝对不会丢失
        memory.save()
        print(f"  [批次 {batch_num}/{total_batches} 落地完毕] 已累计: 废纸篓 {deleted_count} | 系统通知 {notif_archived_count} | 商业推广 {promo_archived_count} | 通用归档 {gen_archived_count} | 保留 {len(kept_items)}")

    if client.imap:
        client.close()

    # 汇报简报
    date_str = now_dt.strftime("%Y-%m-%d")
    print(f"\n[任务统计] 本次处理历史邮件 {processed_count} 封: 移入废纸篓 {deleted_count} 封 | 归档通知 {notif_archived_count} 封 | 归档推广 {promo_archived_count} 封 | 通用归档 {gen_archived_count} 封 | 保留收件箱 {len(kept_items)} 封")

    # 当处理了邮件时，发送简要邮件告知用户清理进度
    if processed_count > 0:
        html_body = render_history_email_report(
            date_str=date_str,
            processed_count=processed_count,
            deleted_count=deleted_count,
            notif_archived_count=notif_archived_count,
            promo_archived_count=promo_archived_count,
            gen_archived_count=gen_archived_count,
            kept_items=kept_items,
        )
        subject = f"[Inbox Agent] 历史邮件整理报告: 清理{deleted_count}封 | 归档{notif_archived_count + promo_archived_count + gen_archived_count}封 | 保留{len(kept_items)}封"
        preview_path = Path(__file__).resolve().parent / "preview_history.html"
        try:
            send_email_html(
                subject=subject,
                html_content=html_body,
                gmail_user=GMAIL_USER,
                gmail_pass=GMAIL_APP_PASS,
                receiver=NOTIFICATION_EMAIL,
                is_ci=IS_CI,
                preview_path=preview_path,
            )
        except Exception as e:
            print(f"[Email Warning] 发送历史整理报告失败: {e}")

    # 保存加密状态
    memory.save()
    print("=== [Inbox History Agent] 任务完成，状态已加密保存 ===")


if __name__ == "__main__":
    main()
