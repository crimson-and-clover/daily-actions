"""
Inbox Agent (智能邮件助手)
基于 ReAct 驱动的自动化邮件分类、日程提取与简报分发工具。

整体流水线分为六个核心阶段：
1. 身份鉴权与 IMAP 服务组装：连接 Gmail 并初始化 MessageRepo, LabelService 等服务组件；
2. 增量抓取与防重过滤：拉取近 N 天邮件，以全局唯一 Message-ID 排除历史已处置邮件；
3. 批处理 ReAct 智能分流：以 10 封为独立上下文单元，驱动大模型自主调用工具执行打标/日程/草稿；
4. 垃圾箱误杀复核托管：按批次复核被 Google 拦截的 Spam 邮件，主动发现并捞回正常邮件；
5. 日程池唤醒与维护：依据当前日期计算到期/预警日程，淘汰过期失效日程；
6. 结构化简报多渠道分发：渲染高信息密度 HTML 邮件日报并发送，持久化加密记忆库。
"""

import sys
from datetime import datetime, timedelta
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
from inbox_agent.imap import (
    DraftService,
    FlagService,
    ImapConnection,
    LabelService,
    MessageRepo,
)
from inbox_agent.imap.models import Email
from inbox_agent.memory import InboxMemory
from inbox_agent.renderer import render_email_report
from inbox_agent.rules import is_internal_ci
from inbox_agent.tools import ToolContext
from inbox_agent.tracker import BatchTracker
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
    # 基础配置项校验：确保模型 API KEY 与 Gmail 鉴权信息齐全
    validate_config(require_deepseek=True)
    now_dt = get_now_bjt()
    print(f"=== [Inbox Agent] 智能邮件助手启动 ({now_dt.strftime('%Y-%m-%d %H:%M:%S')} BJT) ===")

    # -------------------------------------------------------------------------
    # 阶段 1: 身份鉴权与 IMAP 协议/服务组件初始化
    # -------------------------------------------------------------------------
    memory = InboxMemory()
    conn = ImapConnection(username=GMAIL_USER, password=GMAIL_APP_PASS)

    print("[IMAP] 正在连接 Gmail 检查收件箱与垃圾箱...")
    try:
        conn.connect()
    except Exception as e:
        print(f"[IMAP Fatal Error] Gmail 登录/鉴权失败: {e}", file=sys.stderr)
        sys.exit(1)

    # 组装领域服务矩阵：仓储、标签、旗标与草稿服务
    repo = MessageRepo(conn)
    label_service = LabelService(conn)
    flag_service = FlagService(conn)
    draft_service = DraftService(conn)

    # -------------------------------------------------------------------------
    # 阶段 2: 邮件增量抓取与防御性防重过滤
    # -------------------------------------------------------------------------
    # 抓取最近 FETCH_DAYS_LIMIT 天内的邮件，避免每次全量下载海量历史邮件
    since_date = (now_dt - timedelta(days=FETCH_DAYS_LIMIT)).strftime("%d-%b-%Y")
    criteria = ["SINCE", since_date]

    try:
        # fetch_emails 内部已通过 Header PEEK Message-ID 预检跳过已处理邮件，返回纯净 Email 强类型对象
        raw_emails = repo.fetch_emails(
            code="inbox",
            criteria=criteria,
            limit=MAX_EMAILS_PER_RUN,
            is_processed_func=memory.is_processed,
        )
        print(f"[IMAP] 获取到收件箱近期邮件: {len(raw_emails)} 封")
    except Exception as e:
        print(f"[IMAP Fatal Error] 获取收件箱邮件异常: {e}", file=sys.stderr)
        conn.close()
        sys.exit(1)

    # 应用层二次防重过滤：确保绝对不重复研判已沉淀至记忆库的邮件
    unprocessed_emails = [e for e in raw_emails if not memory.is_processed(e.message_id)]
    print(f"[过滤] 待分类新邮件: {len(unprocessed_emails)} 封 (已跳过历史处理邮件 {len(raw_emails) - len(unprocessed_emails)} 封)")

    tracker = BatchTracker()
    context = ToolContext(
        connection=conn,
        repo=repo,
        label_service=label_service,
        flag_service=flag_service,
        draft_service=draft_service,
        memory=memory,
        current_code="inbox",
    )
    engine = AgentEngine(api_key=DEEPSEEK_API_KEY)

    # -------------------------------------------------------------------------
    # 阶段 2.5: 内部自动化与系统报告硬规则预过滤 (Rule-based Pre-filter)
    # -------------------------------------------------------------------------
    # 内部 CI 邮件（如 [Inbox Agent] 简报等）直接规则归档，严禁进入 Agent，杜绝 Token 消耗与日程套娃
    rule_filtered_emails: list[Email] = []
    agent_emails: list[Email] = []

    for e in unprocessed_emails:
        if is_internal_ci(e.subject, sender=e.from_addr, my_email=GMAIL_USER):
            rule_filtered_emails.append(e)
        else:
            agent_emails.append(e)

    if rule_filtered_emails:
        rule_uids = [e.uid for e in rule_filtered_emails if e.uid]
        print(f"[规则预过滤] 命中 {len(rule_filtered_emails)} 封内部自动化/CI 邮件，直接规则归档至系统通知目录并标记已处理...")
        tracker.register_batch_emails(rule_filtered_emails)
        archive_success = False
        if rule_uids:
            try:
                label_service.set_labels(
                    uids=rule_uids,
                    add=["system_notification"],
                    remove=["inbox"],
                )
                tracker.record_labels(
                    uids=rule_uids,
                    add=["system_notification"],
                    remove=["inbox"],
                    tldr="系统自动化任务简报/CI通知（硬规则自动归档）",
                )
                archive_success = True
            except Exception as e:
                print(f"[规则预过滤 Warning] 归档内部 CI 邮件失败: {e}，跳过标记已处理以便下次重试", file=sys.stderr)

        if archive_success:
            for e in rule_filtered_emails:
                if e.message_id:
                    memory.mark_processed(e.message_id)
            memory.save()

    # -------------------------------------------------------------------------
    # 阶段 3: 批处理 ReAct 智能分流与决策执行
    # -------------------------------------------------------------------------
    total_unprocessed = len(agent_emails)
    total_batches = (total_unprocessed + BATCH_SIZE - 1) // BATCH_SIZE if total_unprocessed > 0 else 0

    # 分批执行收件箱新邮件研判与分流 (每批 10 封，开启全新独立对话上下文，杜绝 Token 膨胀)
    for batch_idx in range(0, total_unprocessed, BATCH_SIZE):
        batch = agent_emails[batch_idx : batch_idx + BATCH_SIZE]
        batch_num = (batch_idx // BATCH_SIZE) + 1
        print(f"\n--- [批次 {batch_num}/{total_batches}] 正在由 Agent 处理 {len(batch)} 封收件箱新邮件 ---")

        # 启动当前批次的 ReAct 循环，模型自主调用工具，结果实时反馈给 tracker
        summary = engine.run_batch_triage(
            batch_emails=batch,
            batch_num=batch_num,
            total_batches=total_batches,
            context=context,
            user_email=GMAIL_USER,
            tracker=tracker,
        )
        print(f"  [批次 {batch_num}/{total_batches} 总结]: {summary}")

        # 【核心容灾设计】每完成一个批次立即落盘保存 Fernet AES 加密记忆库！
        # 即使后续网络偶发闪断或 GitHub Actions 运行超时，前面已完成的批次也绝对不会丢失
        memory.save()
        print(f"  [批次进度已保存] 累计移动: 商业推广 {tracker.marketings_moved_count} | 系统通知 {tracker.systems_moved_count} | 垃圾箱 {tracker.spams_moved_count}")

    # -------------------------------------------------------------------------
    # 阶段 4: 垃圾箱误杀复核托管 (从 [Gmail]/Spam 中解救被误杀的正常邮件)
    # -------------------------------------------------------------------------
    raw_spam_emails: list[Email] = []
    try:
        raw_spam_emails = repo.fetch_emails(
            code="spam",
            criteria=criteria,
            limit=30,
            is_processed_func=memory.is_processed,
        )
        print(f"\n[IMAP] 获取到垃圾箱近期待复核邮件: {len(raw_spam_emails)} 封")
    except Exception as e:
        print(f"\n[IMAP Warning] 获取垃圾箱待复核邮件异常: {e}，跳过垃圾箱复核", file=sys.stderr)

    unprocessed_spams = [e for e in raw_spam_emails if not memory.is_processed(e.message_id)]
    if unprocessed_spams:
        total_unprocessed_spams = len(unprocessed_spams)
        total_spam_batches = (total_unprocessed_spams + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"\n[垃圾箱复核] 开始分批复核 {total_unprocessed_spams} 封垃圾箱拦截邮件 (共 {total_spam_batches} 批)...")

        # 切换当前目录上下文为 spam，告知模型此时正在复核垃圾箱
        context.current_code = "spam"
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
                tracker=tracker,
            )
            print(f"  [垃圾箱复核批次 {s_batch_num}/{total_spam_batches} 总结]: {s_summary}")

            # 将本批经 Agent 复核后确认未解救（依然属于真实垃圾）的邮件标记为 processed(is_spam=True)
            for item in s_batch:
                m_id = item.message_id
                uid = item.uid
                is_rescued = any(r.get("uid") == uid for r in tracker.rescued_items)
                if not is_rescued and m_id and not memory.is_processed(m_id):
                    memory.mark_processed(m_id, is_spam=True)
            memory.save()

    # 所有 IMAP 交互与工具调用完毕，安全关闭连接
    conn.close()

    # -------------------------------------------------------------------------
    # 阶段 5: 日程池唤醒、到期预警与过期清理
    # -------------------------------------------------------------------------
    date_str = now_dt.strftime("%Y-%m-%d")
    run_slot = get_run_slot_name(now_dt)

    # 根据大模型提取的 advance_days 提前预警天数，提取今日到期或提前预警的日程待办
    today_due_schedules = memory.get_due_schedules(now=now_dt)
    # 自动清理历史已逾期超过 3 天的事项，保持活跃日程池干练精炼
    memory.prune_expired_schedules(now=now_dt)

    # -------------------------------------------------------------------------
    # 阶段 6: 邮件简报渲染与通知分发
    # -------------------------------------------------------------------------
    email_html = render_email_report(
        date_str=now_dt.strftime("%Y-%m-%d %H:%M"),
        run_slot=run_slot,
        schedules=tracker.schedules,
        today_due_schedules=today_due_schedules,
        importants=tracker.importants,
        systems=tracker.systems,
        marketings=tracker.marketings,
        spams=tracker.spams,
        marketings_moved_count=tracker.marketings_moved_count,
        systems_moved_count=tracker.systems_moved_count,
        spams_moved_count=tracker.spams_moved_count,
        rescued_items=tracker.rescued_items,
    )

    # 邮件标题：遵循无 Emoji、高信息密度与关键统计显式呈现规范
    due_today_tag = f" | 今日到期{len(today_due_schedules)}项" if today_due_schedules else ""
    subject = (
        f"[Inbox Agent] {date_str} 收件箱简报[{run_slot}]: "
        f"{len(tracker.schedules)}项新增待办{due_today_tag} | "
        f"{len(tracker.importants)}封重要 | "
        f"归档{tracker.systems_moved_count}封通知 | "
        f"隔离{tracker.marketings_moved_count}封营销 | "
        f"移入{tracker.spams_moved_count}封垃圾"
    )
    preview_email_path = Path(__file__).resolve().parent / "preview_email.html"

    # 执行邮件发送并确保最终状态落盘
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
