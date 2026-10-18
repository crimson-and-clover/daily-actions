"""
CCF-DDL 顶会日程实时分析与审稿窗口推导引擎
基于全球学术开源社区 ccfddl/ccf-deadlines 实时数据，秒级研判各大顶会审稿与救火黄金窗口
"""

import re
from datetime import datetime
from typing import Any

import requests

from reviewer_radar.models import ConferencePhase, ConferenceTarget
from utils.timezone import get_now_bjt

# 核心跟踪的计算机视觉/多模态/人工智能顶会配置列表
TRACKED_CONFERENCE_CONFIGS: list[dict[str, Any]] = [
    # AI 赛道
    {"category": "AI", "file": "cvpr.yml", "openreview_prefix": "thecvf.com/CVPR"},
    {"category": "AI", "file": "iccv.yml", "openreview_prefix": "thecvf.com/ICCV"},
    {"category": "AI", "file": "eccv.yml", "openreview_prefix": "ECCV"},
    {"category": "AI", "file": "iclr.yml", "openreview_prefix": "ICLR.cc"},
    {"category": "AI", "file": "nips.yml", "openreview_prefix": "NeurIPS.cc"},
    {"category": "AI", "file": "icml.yml", "openreview_prefix": "ICML.cc"},
    {"category": "AI", "file": "aaai.yml", "openreview_prefix": "AAAI.org"},
    {"category": "AI", "file": "ijcai.yml", "openreview_prefix": "IJCAI"},
    {"category": "AI", "file": "wacv.yml", "openreview_prefix": "WACV"},
    {"category": "AI", "file": "bmvc.yml", "openreview_prefix": "BMVC"},
    # 计算机图形学与多媒体赛道 (CG)
    {"category": "CG", "file": "mm.yml", "openreview_prefix": "ACM.org/MM"},
    {"category": "CG", "file": "sig.yml", "openreview_prefix": "SIGGRAPH"},
    {"category": "CG", "file": "siga.yml", "openreview_prefix": "SIGGRAPH_Asia"},
    {"category": "CG", "file": "3dv.yml", "openreview_prefix": "3DV"},
]

RAW_BASE_URL = "https://raw.githubusercontent.com/ccfddl/ccf-deadlines/main/conference"


def parse_ccf_yaml_content(text: str) -> dict[str, Any]:
    """轻量解析 CCF-DDL 单个会务 YAML 文件 (零第三方 YAML 依赖，高效安全)"""
    # 提取标题
    m_title = re.search(r"title:\s*([A-Za-z0-9_-]+)", text)
    title = m_title.group(1) if m_title else "UNKNOWN"

    # 提取 CCF 评级
    m_rank = re.search(r"ccf:\s*([A-C])", text)
    rank = m_rank.group(1) if m_rank else "A"

    confs_data = []
    # 拆分每一个 conf 周期块
    blocks = re.split(r"-\s+year:\s*", text)[1:]
    for b in blocks:
        lines = b.splitlines()
        if not lines:
            continue
        y_str = lines[0].strip()
        if not y_str.isdigit():
            continue
        year = int(y_str)

        m_link = re.search(r"link:\s*([^\s]+)", b)
        link = m_link.group(1) if m_link else ""

        # 提取 deadline
        m_dl = re.search(r"deadline:\s*['\"]?([0-9]{4}-[0-9]{2}-[0-9]{2})", b)
        deadline = m_dl.group(1) if m_dl else None

        # 提取 rebuttal
        m_reb = re.search(r"rebuttal_deadline:\s*['\"]?([0-9]{4}-[0-9]{2}-[0-9]{2})", b)
        rebuttal = m_reb.group(1) if m_reb else None

        if deadline:
            confs_data.append({
                "year": year,
                "link": link,
                "deadline": deadline,
                "rebuttal": rebuttal,
            })

    return {
        "title": title,
        "rank": rank,
        "confs": confs_data,
    }


def fetch_conference_targets(now_dt: datetime | None = None) -> list[ConferenceTarget]:
    """联网拉取并解析所有跟踪顶会的最新日程与生命周期阶段"""
    if now_dt is None:
        now_dt = get_now_bjt()

    # 抹平时间方便做纯日期天数比对
    current_date = datetime(now_dt.year, now_dt.month, now_dt.day)
    targets: list[ConferenceTarget] = []

    # 关注当前年与下一年两个轮转年
    candidate_years = [now_dt.year, now_dt.year + 1]

    for conf_cfg in TRACKED_CONFERENCE_CONFIGS:
        cat = conf_cfg["category"]
        fname = conf_cfg["file"]
        url = f"{RAW_BASE_URL}/{cat}/{fname}"

        try:
            resp = requests.get(url, timeout=6)
            if resp.status_code != 200:
                continue
            parsed = parse_ccf_yaml_content(resp.text)
            title = parsed["title"]
            rank = parsed["rank"]

            for c in parsed["confs"]:
                year = c["year"]
                if year not in candidate_years:
                    continue

                dl_str = c["deadline"]
                dld = datetime.strptime(dl_str, "%Y-%m-%d")
                diff_days = (current_date - dld).days

                # 阶段与中文标签研判
                if diff_days < -30:
                    phase = ConferencePhase.PRE_DEADLINE
                    label = "⏳ 筹备预热中 (距离截稿较远)"
                elif -30 <= diff_days < 0:
                    phase = ConferencePhase.PRE_DEADLINE
                    label = f"⏰ 即将截稿 (倒计时 {-diff_days} 天，主会/Workshop Reviewer 招募启动)"
                elif 0 <= diff_days <= 60:
                    phase = ConferencePhase.ACTIVE_REVIEW
                    label = f"🔥 正审与救火黄金期 (截稿第 {diff_days} 天，Emergency Reviewer 高发)"
                elif 60 < diff_days <= 120:
                    phase = ConferencePhase.REBUTTAL_DECISION
                    label = f"⚡ 冲刺救火/Rebuttal期 (截稿第 {diff_days} 天)"
                else:
                    phase = ConferencePhase.CONCLUDED
                    label = "🏁 审稿已闭幕"

                # 动态补全该年度的 OpenReview 前缀
                base_or_prefix = conf_cfg.get("openreview_prefix")
                or_prefix = f"{base_or_prefix}/{year}" if base_or_prefix else None

                target = ConferenceTarget(
                    title=title,
                    year=year,
                    ccf_rank=rank,
                    deadline=dl_str,
                    rebuttal_deadline=c.get("rebuttal"),
                    diff_days=diff_days,
                    phase=phase,
                    phase_label_zh=label,
                    official_url=c["link"],
                    openreview_prefix=or_prefix,
                )
                targets.append(target)
        except Exception:
            continue

    return targets


def get_active_conference_targets(now_dt: datetime | None = None) -> list[ConferenceTarget]:
    """
    过滤出当前正处于审稿人招募、正审与救火【黄金窗口期】的高价值顶会
    窗口定义: 截稿前 30 天 至 截稿后 120 天
    """
    all_targets = fetch_conference_targets(now_dt)
    # 严格按关注度过滤
    active = [t for t in all_targets if -30 <= t.diff_days <= 120]
    # 按紧迫程度排序（即将截稿与正在救火的排在最前）
    active.sort(key=lambda x: x.diff_days)
    return active
