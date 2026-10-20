"""
Reviewer Radar Agent 总调度与执行入口
协调官网爬虫、OpenReview 扫描、Workshop 雷达与 DeepSeek 研判，为用户推送审稿机会
"""

from pathlib import Path

from reviewer_radar.analyzer import analyze_and_generate_pitch
from reviewer_radar.config import (
    GMAIL_APP_PASS,
    GMAIL_USER,
    IS_CI,
    NOTIFICATION_EMAIL,
    validate_config,
)
from reviewer_radar.memory import RadarMemory
from reviewer_radar.openreview_radar import scan_openreview_invitations
from reviewer_radar.renderer import render_reviewer_email
from reviewer_radar.web_crawler import scan_all_conference_websites
from reviewer_radar.workshop_radar import scan_top_workshops
from utils.mailer import send_email_html
from utils.timezone import get_now_bjt


def run_reviewer_radar() -> None:
    """执行审稿雷达主任务"""
    now_bjt = get_now_bjt()
    now_bjt_str = now_bjt.strftime("%Y-%m-%d %H:%M:%S")
    print(f"🚀 [{now_bjt_str}] Reviewer Radar (NIW 专版) 启动运行...")

    validate_config()
    memory = RadarMemory()

    # 1. 多源并行采集
    raw_candidates = []

    # 渠道 A: 顶级会议官网
    web_opps = scan_all_conference_websites()
    raw_candidates.extend(web_opps)

    # 渠道 B: OpenReview 官方 API
    openreview_opps = scan_openreview_invitations()
    raw_candidates.extend(openreview_opps)

    # 渠道 C: 顶会官方 Workshops
    workshop_opps = scan_top_workshops()
    raw_candidates.extend(workshop_opps)

    print(f"📊 [Reviewer Radar] 初始感知到 {len(raw_candidates)} 个候选审稿招募/表单线索")

    # 2. 内存过滤与去重
    fresh_candidates = []
    for opp in raw_candidates:
        form_url = opp.get("form_url") or opp.get("source_url")
        if not form_url:
            continue
        if memory.is_notified(form_url):
            continue
        fresh_candidates.append(opp)

    print(f"🔍 [Reviewer Radar] 过滤掉已通知项目后，剩余 {len(fresh_candidates)} 个未通知的潜在机会")

    if not fresh_candidates:
        print("✅ [Reviewer Radar] 本次运行未发现新的审稿招募或救火机会，系统待命中。")
        memory.save(run_timestamp=now_bjt_str)
        return

    # 3. DeepSeek 语义深度研判与定制自荐信生成
    verified_opportunities = []
    for raw_opp in fresh_candidates:
        print(f"🤖 [Reviewer Radar] 正在调用 DeepSeek 分析: {raw_opp.get('title')}")
        analyzed = analyze_and_generate_pitch(raw_opp)
        if analyzed and analyzed.get("is_valid", False):
            verified_opportunities.append(analyzed)

    print(f"🎯 [Reviewer Radar] 经 DeepSeek 严格研判，确认有效审稿机会共 {len(verified_opportunities)} 个！")

    if not verified_opportunities:
        print("ℹ️ [Reviewer Radar] 候选项目均为普通征文(Call for Papers)或已失效，不发送邮件。")
        memory.save(run_timestamp=now_bjt_str)
        return

    # 4. 渲染 HTML 邮件并发送
    email_html = render_reviewer_email(
        opportunities=verified_opportunities,
        run_time_bjt=now_bjt_str,
    )
    email_subject = f"🎯 [审稿机会速递] 为您捕获到 {len(verified_opportunities)} 个顶会/Workshop 审稿招募 (NIW 专版)"

    preview_path = Path(__file__).resolve().parent / "preview_email.html"

    print("📬 [Reviewer Radar] 正在发送通知邮件...")
    send_email_html(
        subject=email_subject,
        html_content=email_html,
        gmail_user=GMAIL_USER,
        gmail_pass=GMAIL_APP_PASS,
        receiver=NOTIFICATION_EMAIL,
        is_ci=IS_CI,
        preview_path=preview_path,
    )

    # 5. 记录已通知状态并持久化
    for item in verified_opportunities:
        target_url = item.get("form_url") or item.get("original_opp", {}).get("form_url")
        if target_url:
            memory.record_notification(
                opp_id=target_url,
                info={
                    "conference": item.get("conference_name"),
                    "type": item.get("recruitment_type"),
                    "notified_at": now_bjt_str,
                },
            )

    memory.save(run_timestamp=now_bjt_str)
    print("🎉 [Reviewer Radar] 本次雷达探测与通知流程顺利完成！")


if __name__ == "__main__":
    run_reviewer_radar()
