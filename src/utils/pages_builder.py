"""
GitHub Pages 静态门户与专区索引页面生成公共模块 (Pages Builder)
负责生成/更新全站知识门户 (docs/index.html) 以及各任务专区的历史研报索引页 (docs/{agent}/index.html)
"""

from pathlib import Path

from utils.prompt_loader import render_global_html_template


def render_section_index(
    title: str,
    badge: str,
    description: str,
    latest_date: str,
    latest_title: str,
    archives_dir: Path,
    summary_suffix: str = "深度研报",
) -> str:
    """
    渲染各专区历史研报二级索引页 (使用 templates/section_index.html)
    自动扫描 archives_dir 下的所有 .html 报告，按降序排列
    """
    archives = []
    if archives_dir.exists():
        html_files = sorted(archives_dir.glob("*.html"), key=lambda p: p.name, reverse=True)
        for p in html_files:
            d = p.stem
            archives.append({"date": d, "summary": f"{d} {summary_suffix}"})

    return render_global_html_template(
        "section_index.html",
        title=title,
        badge=badge,
        description=description,
        latest_date=latest_date,
        latest_title=latest_title,
        archives=archives,
    )


def update_portal_index(docs_root: Path) -> str:
    """
    更新或生成 GitHub Pages 根目录全站多 CI 导航门户 (docs/index.html)
    返回渲染生成的 HTML 内容
    """
    docs_root.mkdir(parents=True, exist_ok=True)
    root_index_path = docs_root / "index.html"

    portal_html = render_global_html_template("portal.html")
    root_index_path.write_text(portal_html, encoding="utf-8")

    print(f"[门户更新] 全站多CI知识门户已同步: {root_index_path}", flush=True)
    return portal_html
