"""
全球宏观、财经与计算开源观察内参 (Global Intelligence, Markets & Technology Briefing)
数据源多源扩充 + AI 多维度评估 + 市场与资产定价传导分析

本文件为工作流与执行主入口，已模块化解耦：
- config.py:   全局常量、时间、路径与数据源配置
- fetcher.py:  RSS/API 数据抓取与去重清洗
- analyzer.py: DeepSeek 多维量化打分与市场传导研判
- renderer.py: 报告与索引页面 HTML 渲染
"""

import sys

from utils.mailer import send_email_html
from utils.pages_builder import render_section_index, update_portal_index
from world_news.analyzer import analyze_with_deepseek
from world_news.config import (
    ARCHIVES_DIR,
    DEEPSEEK_API_KEY,
    DOCS_DIR,
    DOCS_ROOT,
    GMAIL_APP_PASS,
    GMAIL_USER,
    IS_CI,
    MAX_NEWS_AGE_DAYS,
    NOTIFICATION_EMAIL,
    PAGES_BASE_URL,
    PREVIEW_REPORT_PATH,
    get_now_bjt,
    validate_config,
)
from world_news.fetcher import (
    clean_html,
    fetch_macro_finance_feeds,
    fetch_tech_opensource_feeds,
)
from world_news.memory import WorldNewsMemory
from world_news.renderer import build_html_report

# 符号导出以保持向下兼容
__all__ = [
    "WorldNewsMemory",
    "clean_html",
    "fetch_macro_finance_feeds",
    "fetch_tech_opensource_feeds",
    "analyze_with_deepseek",
    "render_section_index",
    "build_html_report",
    "main",
]


def main():
    validate_config()
    now_dt = get_now_bjt()
    print(f"[{now_dt.strftime('%Y-%m-%d %H:%M:%S')}] 开始生成多源宏观财经与计算开源内参 (多维评分版)...")

    # 0. 初始化状态持久化库 (历史资讯去重与记录)
    memory = WorldNewsMemory()
    print(f"[状态加载] 已记录已处理资讯: {len(memory.data.get('seen_urls', []))} 条 URLs, {len(memory.data.get('seen_titles', []))} 条标题")

    # 1. 抓取候选素材 (带 3 天时效过滤与已处理过滤)
    macro_items = fetch_macro_finance_feeds(memory=memory, max_age_days=MAX_NEWS_AGE_DAYS)
    print(f"已获取 {len(macro_items)} 条宏观与财经候选素材 (CNBC / BBC / WSJ / Bloomberg)")

    tech_items = fetch_tech_opensource_feeds(memory=memory, max_age_days=MAX_NEWS_AGE_DAYS)
    print(f"已获取 {len(tech_items)} 条科技与开源前沿素材 (Hacker News / GitHub Trending)")

    # 2. 调用 AI 展开多维度评估与市场传导研判
    ai_analysis = analyze_with_deepseek(macro_items, tech_items, DEEPSEEK_API_KEY)
    if not ai_analysis:
        print("[Fatal Error] 大模型深度分析与多源降噪失败！", file=sys.stderr)
        sys.exit(1)

    # 3. 标记本次已评估处理素材并持久化状态
    for item in macro_items:
        memory.mark_seen(url=item.get("link", ""), title=item.get("title", ""))
    for item in tech_items:
        memory.mark_seen(url=item.get("url", ""), title=item.get("title", ""))
    memory.save()

    date_str = now_dt.strftime("%Y-%m-%d")

    # 4. 保存当日内参详情页面到 archives/{date}.html
    ARCHIVES_DIR.mkdir(parents=True, exist_ok=True)
    date_path = ARCHIVES_DIR / f"{date_str}.html"
    web_html = build_html_report(macro_items, tech_items, ai_analysis, pages_url=None)
    date_path.write_text(web_html, encoding="utf-8")
    print(f"[网页生成] 内参正文已保存至归档: {date_path}")

    # 5. 渲染专区聚合索引页到 world-news/index.html
    section_index_html = render_section_index(
        title="全球宏观、市场与计算开源内参",
        badge="CI: WORLD NEWS & INTELLIGENCE",
        description="多源一手聚合、LLM Impact Score 严格量化评级、资本市场与资产定价传导逻辑深度推演。",
        latest_date=date_str,
        latest_title=f"全球宏观政经与开源内参 ({date_str})",
        archives_dir=ARCHIVES_DIR,
    )
    index_path = DOCS_DIR / "index.html"
    index_path.write_text(section_index_html, encoding="utf-8")
    print(f"[网页生成] 资讯专区索引主页已更新: {index_path}")

    # 6. 生成或更新 GitHub Pages 根目录导航页 (docs/index.html)
    update_portal_index(DOCS_ROOT)

    # 7. 生成邮件版本 HTML 并发送
    pages_today_url = f"{PAGES_BASE_URL.rstrip('/')}/world-news/archives/{date_str}.html"
    email_html = build_html_report(macro_items, tech_items, ai_analysis, pages_url=pages_today_url)

    # 提取头条核心看点，生成高信息密度干练主题 (去除Emoji)
    headline_brief = ""
    if ai_analysis and ai_analysis.get("key_signals"):
        first_signal = ai_analysis["key_signals"][0].strip()
        headline_brief = f": {first_signal[:35]}"
    elif ai_analysis and ai_analysis.get("world_events"):
        first_event = ai_analysis["world_events"][0].get("title", "").strip()
        headline_brief = f": {first_event[:35]}"

    subject = f"[World News] {date_str} 全球宏观、市场与计算开源内参{headline_brief}"
    send_email_html(
        subject=subject,
        html_content=email_html,
        gmail_user=GMAIL_USER,
        gmail_pass=GMAIL_APP_PASS,
        receiver=NOTIFICATION_EMAIL,
        is_ci=IS_CI,
        preview_path=PREVIEW_REPORT_PATH,
    )
    print("内参流程执行完成！")


if __name__ == "__main__":
    main()
