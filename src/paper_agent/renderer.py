"""
研报页面与邮件模板渲染模块
"""

from paper_agent.config import (
    RESEARCH_TRACKS,
    TEMPLATES_HTML_DIR,
)
from utils.prompt_loader import render_html_template


def prepare_tracks_data(track_results: dict) -> list:
    """整理待渲染的文献数据结构"""
    tracks_data = []
    for track in RESEARCH_TRACKS:
        papers = track_results.get(track["id"], [])
        formatted_papers = []
        for p in papers:
            full_info = p.get("full_content", {})
            reasoning = p.get("reasoning", {}) or {}

            formatted_papers.append(
                {
                    "id": p["id"],
                    "title": p["title"],
                    "authors": p["authors"],
                    "published": p["published"],
                    "link": p["link"],
                    "pdf": p["pdf"],
                    "html_url": p["html_url"],
                    "has_full_text": full_info.get("has_full_text", False),
                    "github_url": full_info.get("github_urls", [None])[0] if full_info.get("github_urls") else None,
                    "github_urls": full_info.get("github_urls", [])[:1],
                    "figures": full_info.get("figures", []),
                    "reasoning": reasoning,
                }
            )
        tracks_data.append({"tag": track["tag"], "papers": formatted_papers})
    return tracks_data


def render_web_report_html(tracks_data: list, total_seen_count: int, date_str: str) -> str:
    """渲染适用于 GitHub Pages 的完整版 HTML (包含 KaTeX 与 CSS Grid)"""
    today_count = sum(len(track["papers"]) for track in tracks_data)
    return render_html_template(
        TEMPLATES_HTML_DIR,
        "web.html",
        date_str=date_str,
        today_count=today_count,
        total_seen_count=total_seen_count,
        tracks=tracks_data,
    )


def render_email_report_html(tracks_data: list, total_seen_count: int, date_str: str, pages_url: str = None) -> str:
    """渲染适用于 Gmail 邮件客户端的极简版 HTML (纯 Table 布局、白话概述与打分，引导至 Pages)"""
    today_count = sum(len(track["papers"]) for track in tracks_data)
    return render_html_template(
        TEMPLATES_HTML_DIR,
        "email.html",
        date_str=date_str,
        today_count=today_count,
        total_seen_count=total_seen_count,
        tracks=tracks_data,
        pages_url=pages_url,
    )
