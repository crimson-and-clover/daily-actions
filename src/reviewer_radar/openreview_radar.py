"""
OpenReview 平台官方 API 审稿招募/救火雷达
针对 NeurIPS, ICLR, ICML, CVPR 等在 OpenReview 托管的顶会
"""

import time

import openreview

# 聚焦当前活跃周期及最新筹备中的顶会 Venue
ACTIVE_VENUES = [
    "NeurIPS.cc/2025/Conference",
    "NeurIPS.cc/2026/Conference",
    "ICLR.cc/2026/Conference",
    "ICML.cc/2025/Conference",
    "ICML.cc/2026/Conference",
    "thecvf.com/CVPR/2026/Conference",
]

# 重点探测的核心招募/救火 Invitation
RECRUITMENT_SUFFIXES = [
    "Reviewer_Recruitment",
    "Volunteer_Reviewer",
    "Emergency_Reviewer",
    "Call_for_Reviewers",
]


def scan_openreview_invitations() -> list[dict]:
    """通过 OpenReview API 扫描各大顶会的审稿招募与救火公开邀请"""
    opportunities = []
    print("📡 [OpenReviewRadar] 开始通过 OpenReview API 扫描顶级 Venue 招募 Invitation...")

    try:
        client_v2 = openreview.api.OpenReviewClient(baseurl="https://api2.openreview.net")
    except Exception as e:
        print(f"⚠️ [OpenReviewRadar] 初始化客户端失败: {e}")
        return opportunities

    for venue in ACTIVE_VENUES:
        conf_short = venue.split("/")[0].replace("thecvf.com", "CVF")
        if "CVPR" in venue:
            conf_short = "CVPR"
        elif "ICCV" in venue:
            conf_short = "ICCV"

        for suffix in RECRUITMENT_SUFFIXES:
            invitation_id = f"{venue}/-/{suffix}"
            try:
                time.sleep(0.1)
                inv = client_v2.get_invitation(invitation_id)
                if inv and getattr(inv, "id", None):
                    due_date = getattr(inv, "duedate", None)
                    print(f"  🎉 [OpenReview 发现招募] {inv.id}")
                    opportunities.append(
                        {
                            "conference": conf_short,
                            "full_name": f"{conf_short} ({venue})",
                            "title": f"[{conf_short}] OpenReview 官方审稿人招募/救火通道: {suffix}",
                            "source_url": f"https://openreview.net/invitation?id={inv.id}",
                            "form_url": f"https://openreview.net/invitation?id={inv.id}",
                            "context": f"Venue: {venue}, Invitation ID: {inv.id}, Due Date: {due_date}",
                            "type": "OpenReview Official Invitation",
                        }
                    )
            except Exception:
                # 若 404 或无权限说明当前未开放该通道，静默略过
                continue

    return opportunities
