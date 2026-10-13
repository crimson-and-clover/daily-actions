"""
GitHub Pages 静态门户与专区索引页面生成公共模块 (Pages Builder)
负责生成/更新全站知识门户 (docs/index.html) 以及各任务专区的历史研报索引页 (docs/{agent}/index.html)
"""

import os
import subprocess
from pathlib import Path

import requests

from utils.prompt_loader import render_global_html_template

__all__ = ["render_section_index", "update_portal_index"]


def _fetch_remote_archive_dates(agent_name: str) -> set[str]:
    """
    尝试从 gh-pages 分支获取该专区的历史报告日期列表。
    优先通过 本地 git ls-tree origin/gh-pages，其次通过 GitHub REST API 兜底。
    确保 CI 临时运行器即使在无历史文件本地检出的情况下，也能完整列出历期所有研报。
    """
    remote_dates = set()

    # 方式 1: 本地 git 查询 origin/gh-pages
    try:
        res = subprocess.run(
            ["git", "ls-tree", "--name-only", "origin/gh-pages", f"{agent_name}/archives/"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0 and res.stdout.strip():
            for line in res.stdout.strip().splitlines():
                filename = Path(line).name
                if filename.endswith(".html"):
                    remote_dates.add(filename[:-5])
    except Exception:
        pass

    # 方式 2: GitHub API 查询 (CI 环境具备 GITHUB_TOKEN 或公开只读访问)
    if not remote_dates:
        try:
            token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
            headers = {"Accept": "application/vnd.github.v3+json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"

            repo_slug = os.getenv("GITHUB_REPOSITORY", "crimson-and-clover/daily-actions")
            url = f"https://api.github.com/repos/{repo_slug}/contents/{agent_name}/archives?ref=gh-pages"
            resp = requests.get(url, headers=headers, timeout=6)
            if resp.status_code == 200 and isinstance(resp.json(), list):
                for item in resp.json():
                    name = item.get("name", "")
                    if name.endswith(".html"):
                        remote_dates.add(name[:-5])
        except Exception:
            pass

    return remote_dates


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
    自动聚合本地 archives_dir 与 gh-pages 远端归档历史，按时间降序排列
    """
    all_dates = set()

    # 1. 扫描本地 archives_dir 目录下的 .html 文件
    if archives_dir.exists():
        for p in archives_dir.glob("*.html"):
            all_dates.add(p.stem)

    # 2. 扫描远端 gh-pages 历史留存归档 (防止 CI 临时运行器磁盘缺少历史文件)
    agent_name = archives_dir.parent.name
    remote_dates = _fetch_remote_archive_dates(agent_name)
    all_dates.update(remote_dates)

    if latest_date:
        all_dates.add(latest_date)

    sorted_dates = sorted(all_dates, reverse=True)
    archives = [{"date": d, "summary": f"{d} {summary_suffix}"} for d in sorted_dates]

    return render_global_html_template(
        "section_index.html",
        title=title,
        badge=badge,
        description=description,
        latest_date=latest_date or (sorted_dates[0] if sorted_dates else ""),
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
