"""
报告与索引渲染模块 (HTML & Section Index Renderer)
"""

from utils.prompt_loader import render_html_template
from world_news.config import (
    SCORE_THRESHOLD,
    TEMPLATES_HTML_DIR,
    get_now_bjt,
)


def format_world_events(macro_items: list, ai_analysis: dict = None) -> list:
    """组装并排序国际宏观与财经事件列表"""
    macro_by_idx = {item["idx"]: item for item in macro_items}
    events_data = []

    if ai_analysis and ai_analysis.get("world_events"):
        for ev in ai_analysis["world_events"]:
            scores = ev.get("scores", {})
            overall = float(scores.get("overall", ev.get("score", SCORE_THRESHOLD)))
            if overall < SCORE_THRESHOLD:
                continue
            orig = macro_by_idx.get(ev.get("idx"), {})
            events_data.append(
                {
                    "scores": {
                        "overall": f"{overall:.1f}",
                        "strategic": f"{float(scores.get('strategic', overall)):.1f}",
                        "market_sensitivity": f"{float(scores.get('market_sensitivity', overall)):.1f}",
                        "structural": f"{float(scores.get('structural', overall)):.1f}",
                    },
                    "score_rationale": ev.get("score_rationale", ""),
                    "tag": ev.get("tag", "宏观财经"),
                    "source": orig.get("source", "综合通讯"),
                    "title": ev.get("title_zh", orig.get("title", "")),
                    "link": orig.get("link", "#"),
                    "facts": ev.get("facts", orig.get("summary", "")),
                    "stakeholders": ev.get("stakeholders", ""),
                    "strategic_impact": ev.get("strategic_impact", ""),
                    "market_impact": ev.get("market_impact", {}),
                    "original_title": orig.get("title", "")[:50] + "...",
                    "published": orig.get("published", ""),
                }
            )
        events_data.sort(key=lambda x: float(x["scores"]["overall"]), reverse=True)
    else:
        # 基础回退模式
        for item in macro_items[:5]:
            events_data.append(
                {
                    "scores": {"overall": "7.0", "strategic": "7.0", "market_sensitivity": "7.0", "structural": "7.0"},
                    "score_rationale": "常规基础收录",
                    "tag": "宏观事件",
                    "source": item.get("source", "公开源"),
                    "title": item["title"],
                    "link": item["link"],
                    "facts": item["summary"],
                    "stakeholders": "",
                    "strategic_impact": "",
                    "market_impact": None,
                    "original_title": item["title"],
                    "published": item["published"],
                }
            )

    return events_data


def format_tech_trends(tech_items: list, ai_analysis: dict = None) -> list:
    """组装并排序计算技术与开源工程前沿列表"""
    tech_by_idx = {item["idx"]: item for item in tech_items}
    trends_data = []

    if ai_analysis and ai_analysis.get("tech_trends"):
        for tr in ai_analysis["tech_trends"]:
            scores = tr.get("scores", {})
            overall = float(scores.get("overall", tr.get("score", SCORE_THRESHOLD)))
            if overall < SCORE_THRESHOLD:
                continue
            orig = tech_by_idx.get(tr.get("idx"), {})
            trends_data.append(
                {
                    "scores": {
                        "overall": f"{overall:.1f}",
                        "technical_novelty": f"{float(scores.get('technical_novelty', overall)):.1f}",
                        "ecosystem_shift": f"{float(scores.get('ecosystem_shift', overall)):.1f}",
                        "production_utility": f"{float(scores.get('production_utility', overall)):.1f}",
                    },
                    "score_rationale": tr.get("score_rationale", ""),
                    "tag": tr.get("tag", "计算工程"),
                    "source": orig.get("source", "开源社区"),
                    "title": tr.get("title_zh", orig.get("title", "")),
                    "link": orig.get("url", "#"),
                    "tech_definition": tr.get("tech_definition", ""),
                    "problem_solved": tr.get("problem_solved", ""),
                    "industry_implication": tr.get("industry_implication", ""),
                    "market_impact": tr.get("market_impact", {}),
                    "hn_link": orig.get("hn_url", "#"),
                    "original_title": orig.get("title", "")[:45] + "...",
                    "hn_score": orig.get("score", 0),
                    "comments": orig.get("comments", 0),
                }
            )
        trends_data.sort(key=lambda x: float(x["scores"]["overall"]), reverse=True)
    else:
        # 基础回退模式
        for s in tech_items[:5]:
            trends_data.append(
                {
                    "scores": {"overall": "7.0", "technical_novelty": "7.0", "ecosystem_shift": "7.0", "production_utility": "7.0"},
                    "score_rationale": "常规基础收录",
                    "tag": "社区前沿",
                    "source": s.get("source", "开源"),
                    "title": s["title"],
                    "link": s["url"],
                    "tech_definition": s["title"],
                    "problem_solved": "",
                    "industry_implication": "",
                    "market_impact": None,
                    "hn_link": s["hn_url"],
                    "original_title": s["title"][:45] + "...",
                    "hn_score": s["score"],
                    "comments": s["comments"],
                }
            )

    return trends_data


def build_html_report(macro_items: list, tech_items: list, ai_analysis: dict = None, pages_url: str = None) -> str:
    """基于独立 report.html 渲染报告（按多维度综合分降序排列）"""
    date_str = get_now_bjt().strftime("%Y年%m月%d日 (北京时间)")
    world_events = format_world_events(macro_items, ai_analysis)
    tech_trends = format_tech_trends(tech_items, ai_analysis)

    key_signals = ai_analysis.get("key_signals", []) if ai_analysis and ai_analysis.get("key_signals") else ["宏观利率", "大宗能源", "云计算基建", "开源重塑"]

    return render_html_template(
        TEMPLATES_HTML_DIR,
        "report.html",
        date_str=date_str,
        executive_summary=ai_analysis.get("executive_summary") if ai_analysis else None,
        key_signals=key_signals,
        world_events=world_events,
        tech_trends=tech_trends,
        pages_url=pages_url,
    )
