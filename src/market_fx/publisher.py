"""
Market FX 页面渲染与发布模块：生成静态归档、专区索引、总门户与邮件分发
"""

from market_fx.config import (
    CURRENT_DIR,
    DOCS_DIR,
    DOCS_ROOT,
    GMAIL_APP_PASS,
    GMAIL_USER,
    IS_CI,
    NOTIFICATION_EMAIL,
    PAGES_BASE_URL,
    TEMPLATES_HTML_DIR,
)
from utils.mailer import send_email_html
from utils.pages_builder import render_section_index, update_portal_index
from utils.prompt_loader import render_html_template


def publish_reports(render_context: dict, iso_date_str: str, subject: str):
    """
    统一发布流程：
    1. 生成并归档当日 Web 版本至 docs/market-fx/archives/{date}.html
    2. 生成专区聚合索引页 docs/market-fx/index.html
    3. 生成/同步 GitHub Pages 根目录多CI门户 docs/index.html
    4. 渲染本地预览 preview_report.html
    5. 发送邮件
    """
    # 1. 静态网页版 (is_web=True, 顶部带两级面包屑返回专区与门户)
    archive_dir = DOCS_DIR / "archives"
    archive_dir.mkdir(parents=True, exist_ok=True)
    date_path = archive_dir / f"{iso_date_str}.html"

    web_html = render_html_template(
        TEMPLATES_HTML_DIR,
        "report.html",
        **render_context,
        is_web=True,
        pages_url=None,
    )
    date_path.write_text(web_html, encoding="utf-8")
    print(f"✅ [静态网页] 当日研报已归档至: {date_path}", flush=True)

    # 2. 渲染专区聚合索引页 (docs/market-fx/index.html)
    section_index_html = render_section_index(
        title="全球宏观市场与主流外汇简报",
        badge="CI: MARKET & FX",
        description="每日高密度全球主流汇率、美股基准指数、宏观大宗商品与出境币种经验分位数评估。",
        latest_date=iso_date_str,
        latest_title=f"全球金融市场与主流外汇简报 ({iso_date_str})",
        archives_dir=archive_dir,
    )
    index_path = DOCS_DIR / "index.html"
    index_path.write_text(section_index_html, encoding="utf-8")
    print(f"✅ [静态网页] 专区聚合索引页已生成: {index_path}", flush=True)

    # 3. 更新 GitHub Pages 根目录导航门户 (docs/index.html)
    update_portal_index(DOCS_ROOT)

    # 4. 本地即时预览文件
    preview_path = CURRENT_DIR / "preview_report.html"
    preview_path.write_text(web_html, encoding="utf-8")
    print(f"✅ [本地预览] 已保存至: {preview_path}", flush=True)

    # 5. 渲染邮件 HTML (带跳转至在线归档的永久链接) 并发送邮件
    pages_today_url = f"{PAGES_BASE_URL.rstrip('/')}/market-fx/archives/{iso_date_str}.html"
    email_html = render_html_template(
        TEMPLATES_HTML_DIR,
        "report.html",
        **render_context,
        is_web=False,
        pages_url=pages_today_url,
    )

    send_email_html(
        subject=subject,
        html_content=email_html,
        gmail_user=GMAIL_USER,
        gmail_pass=GMAIL_APP_PASS,
        receiver=NOTIFICATION_EMAIL,
        is_ci=IS_CI,
        preview_path=preview_path,
    )
