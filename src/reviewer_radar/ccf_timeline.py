"""
CCF-DDL 顶会日程实时分析与审稿窗口推导引擎
基于全球学术开源社区 ccfddl/ccf-deadlines 实时数据，秒级研判各大顶会审稿与救火黄金窗口
"""

import re
import sys
from datetime import datetime
from typing import Any

import requests
import yaml
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from reviewer_radar.models import (
    CcfConferenceRound,
    CcfConferenceSeries,
    ConferencePhase,
    ConferenceTarget,
)
from utils.timezone import get_now_bjt

# 核心跟踪的计算机视觉/多模态/人工智能顶会配置列表
TRACKED_CONFERENCE_CONFIGS: list[dict[str, Any]] = [
    # AI 赛道
    {"category": "AI", "file": "cvpr.yml", "openreview_prefix": "thecvf.com/CVPR"},
    {"category": "AI", "file": "iccv.yml", "openreview_prefix": "thecvf.com/ICCV"},
    {"category": "AI", "file": "eccv.yml", "openreview_prefix": "thecvf.com/ECCV"},
    {"category": "AI", "file": "iclr.yml", "openreview_prefix": "ICLR.cc"},
    {"category": "AI", "file": "nips.yml", "openreview_prefix": "NeurIPS.cc"},
    {"category": "AI", "file": "icml.yml", "openreview_prefix": "ICML.cc"},
    {"category": "AI", "file": "aaai.yml", "openreview_prefix": "AAAI.org"},
    {"category": "AI", "file": "ijcai.yml", "openreview_prefix": "ijcai.org/IJCAI"},
    {"category": "AI", "file": "wacv.yml", "openreview_prefix": "thecvf.com/WACV"},
    {"category": "AI", "file": "bmvc.yml", "openreview_prefix": "BMVC"},
    # 计算机图形学与多媒体赛道 (CG)
    {"category": "CG", "file": "mm.yml", "openreview_prefix": "ACM.org/MM"},
    {"category": "CG", "file": "sig.yml", "openreview_prefix": "ACM.org/SIGGRAPH"},
    {"category": "CG", "file": "siga.yml", "openreview_prefix": "ACM.org/SIGGRAPH_Asia"},
    {"category": "CG", "file": "3dv.yml", "openreview_prefix": "3DV"},
]

RAW_BASE_URL = "https://raw.githubusercontent.com/ccfddl/ccf-deadlines/main/conference"

# 模块级复用 HTTP 连接池，14 场会务配置在同一 Session 上快速复用 HTTPS 握手
_CCF_SESSION = requests.Session()
_CCF_SESSION.headers.update({"User-Agent": "ReviewerRadar/1.0"})


def _parse_iso_date(val: Any) -> str | None:
    """从 CCF-DDL 原始文本字段提取标准的 YYYY-MM-DD 日期，自动过滤空值与待定 TBD"""
    if not val or not isinstance(val, str):
        return None
    val = val.strip()
    if not val or val.upper() == "TBD":
        return None
    cand = val.split()[0]
    return cand if re.match(r"^\d{4}-\d{2}-\d{2}$", cand) else None


def parse_ccf_yaml_content(text: str) -> CcfConferenceSeries:
    """工业级解析 CCF-DDL 单个会务 YAML 数据为 Pydantic 强类型实体，消除字典弱类型隐患"""
    try:
        data = yaml.safe_load(text)
    except Exception:
        return CcfConferenceSeries(title="UNKNOWN", rank="A", confs=[])

    if not data or not isinstance(data, list):
        return CcfConferenceSeries(title="UNKNOWN", rank="A", confs=[])

    root = data[0] if isinstance(data[0], dict) else {}
    title = str(root.get("title") or "UNKNOWN").strip()

    raw_rank = root.get("rank")
    rank = str(raw_rank.get("ccf") if isinstance(raw_rank, dict) else (raw_rank or "A")).strip()

    confs_data: list[CcfConferenceRound] = []
    for conf in root.get("confs", []):
        if not isinstance(conf, dict):
            continue
        year = conf.get("year")
        if not isinstance(year, int):
            continue
        link = str(conf.get("link") or "").strip()

        # 归一化提取各轮次正式截稿日 (deadline) 与 rebuttal 日期，兼顾兼容单值字段
        timelines = conf.get("timeline")
        if isinstance(timelines, list) and timelines:
            items = [t for t in timelines if isinstance(t, dict)]
        elif "deadline" in conf:
            items = [{"deadline": conf.get("deadline"), "comment": ""}]
        else:
            items = []

        for item in items:
            deadline = _parse_iso_date(item.get("deadline"))
            if not deadline:
                continue
            rebuttal = _parse_iso_date(item.get("rebuttal_deadline"))
            comment = str(item.get("comment") or "").strip()
            confs_data.append(
                CcfConferenceRound(
                    year=year,
                    link=link,
                    deadline=deadline,
                    rebuttal=rebuttal,
                    comment=comment,
                )
            )

    return CcfConferenceSeries(
        title=title,
        rank=rank,
        confs=confs_data,
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    retry=retry_if_exception_type((requests.RequestException, TimeoutError)),
    reraise=True,
)
def _fetch_yaml_text(url: str) -> str:
    """带重试保护与 Session 连接池复用的 CCF-DDL 远程 YAML 数据拉取"""
    resp = _CCF_SESSION.get(url, timeout=8)
    resp.raise_for_status()
    # 强制以 UTF-8 读取 GitHub Raw YAML 文本，规避 requests 默认将未带 charset 响应回退为 ISO-8859-1 的乱码缺陷
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = "utf-8"
    return resp.text


def fetch_conference_targets(now_dt: datetime | None = None) -> list[ConferenceTarget]:
    """联网拉取并解析所有跟踪顶会的最新日程与生命周期阶段"""
    if now_dt is None:
        now_dt = get_now_bjt()

    # 抹平时间方便做纯日期天数比对
    current_date = datetime(now_dt.year, now_dt.month, now_dt.day)
    targets: list[ConferenceTarget] = []

    # 关注当前年与下一年两个轮转年
    candidate_years = [now_dt.year, now_dt.year + 1]
    success_fetch_count = 0

    for conf_cfg in TRACKED_CONFERENCE_CONFIGS:
        cat = conf_cfg["category"]
        fname = conf_cfg["file"]
        url = f"{RAW_BASE_URL}/{cat}/{fname}"

        try:
            yaml_text = _fetch_yaml_text(url)
            parsed = parse_ccf_yaml_content(yaml_text)
            success_fetch_count += 1
            title = parsed.title
            rank = parsed.rank

            # 按 year 对多轮次进行聚合，优先保留正处于窗口期或最贴近当前日期的轮次 (彻底解决 WACV/AAAI 多轮截稿被漏报问题)
            confs_by_year: dict[int, list[CcfConferenceRound]] = {}
            for c in parsed.confs:
                y = c.year
                if y in candidate_years:
                    confs_by_year.setdefault(y, []).append(c)

            for year, round_confs in confs_by_year.items():
                def _score_round(item: CcfConferenceRound) -> tuple[int, int]:
                    dld = datetime.strptime(item.deadline, "%Y-%m-%d")
                    dd = (current_date - dld).days
                    # 优先级 0: 处于核心招募与救火窗口 (-30 <= dd <= 120)
                    # 优先级 1: 其它状态，按 abs(dd) 从小到大排序
                    is_in_window = 0 if -30 <= dd <= 120 else 1
                    return (is_in_window, abs(dd))

                best_c = min(round_confs, key=_score_round)
                dl_str = best_c.deadline
                dld = datetime.strptime(dl_str, "%Y-%m-%d")
                diff_days = (current_date - dld).days
                comment_suffix = f" [{best_c.comment}]" if best_c.comment else ""

                # 阶段与中文标签研判
                if diff_days < -30:
                    phase = ConferencePhase.PRE_DEADLINE
                    label = f"⏳ 筹备预热中 (距离截稿较远{comment_suffix})"
                elif -30 <= diff_days < 0:
                    phase = ConferencePhase.PRE_DEADLINE
                    label = f"⏰ 即将截稿 (倒计时 {-diff_days} 天，主会/Workshop Reviewer 招募启动{comment_suffix})"
                elif 0 <= diff_days <= 60:
                    phase = ConferencePhase.ACTIVE_REVIEW
                    label = f"🔥 正审与救火黄金期 (截稿第 {diff_days} 天，Emergency Reviewer 高发{comment_suffix})"
                elif 60 < diff_days <= 120:
                    phase = ConferencePhase.REBUTTAL_DECISION
                    label = f"⚡ 冲刺救火/Rebuttal期 (截稿第 {diff_days} 天{comment_suffix})"
                else:
                    phase = ConferencePhase.CONCLUDED
                    label = f"🏁 审稿已闭幕{comment_suffix}"

                # 动态补全该年度的 OpenReview 前缀
                base_or_prefix = conf_cfg.get("openreview_prefix")
                or_prefix = f"{base_or_prefix}/{year}" if base_or_prefix else None

                target = ConferenceTarget(
                    title=title,
                    year=year,
                    ccf_rank=rank,
                    deadline=dl_str,
                    rebuttal_deadline=best_c.rebuttal,
                    diff_days=diff_days,
                    phase=phase,
                    phase_label_zh=label,
                    official_url=best_c.link,
                    openreview_prefix=or_prefix,
                )
                targets.append(target)
        except Exception as e:
            print(f"[ReviewerRadar] 拉取/解析顶会配置失败 ({url}): {e}", file=sys.stderr)
            continue

    if not targets and success_fetch_count == 0:
        raise RuntimeError("CCF-DDL 顶会日程全量拉取失败，请检查网络或 GitHub Raw 访问状态")

    return targets

