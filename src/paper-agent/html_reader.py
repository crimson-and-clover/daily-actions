"""
arXiv HTML 论文全文高保真解析器
通过 arXiv 官方 HTML 版本 (https://arxiv.org/html/{id}) 或 ar5iv 实验室版本，
提取结构化的正文章节（Introduction, Method/Architecture, Experiments, Limitations）
并过滤掉 References 与致谢等冗余噪点。
"""

import re
import sys
import requests
import bs4

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
}


def clean_text(text: str) -> str:
    """清理多余空白与换行"""
    return re.sub(r'\s+', ' ', text).strip()


def extract_full_paper(arxiv_id: str) -> dict:
    """
    抓取并解析 arXiv 论文 HTML 全文。
    返回结构化的章节正文及项目 GitHub 链接。
    """
    clean_id = arxiv_id.strip()
    if clean_id.startswith("http"):
        clean_id = clean_id.split("/abs/")[-1].split("/html/")[-1]

    urls_to_try = [
        f"https://arxiv.org/html/{clean_id}",
        f"https://ar5iv.labs.arxiv.org/html/{clean_id}"
    ]

    resp = None
    for url in urls_to_try:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 200 and ("ltx_document" in r.text or "ltx_page_main" in r.text):
                resp = r
                break
        except Exception:
            continue

    if not resp:
        return {
            "has_full_text": False,
            "github_urls": [],
            "intro": "",
            "method": "",
            "experiments": "",
            "limitations": "",
            "html_url": f"https://arxiv.org/html/{clean_id}"
        }

    soup = bs4.BeautifulSoup(resp.text, "html.parser")

    # 提取正文中作者声明的 GitHub 开源仓库链接
    raw_gh_links = re.findall(r'https?://github\.com/([\w\-]+/[\w\-]+)', resp.text)
    filtered_gh = set()
    ignored_orgs = {"arxiv", "brucemiller", "github", "actions", "facebookresearch", "google-research"}
    for link in raw_gh_links:
        org = link.split("/")[0].lower()
        if org not in ignored_orgs and not link.endswith((".png", ".jpg", ".svg")):
            filtered_gh.add(f"https://github.com/{link}")

    # 剔除 References、致谢与版权声明元素
    for elem in soup.find_all(['section', 'div', 'span'], class_=['ltx_bibliography', 'ltx_role_ref', 'ltx_copyright']):
        elem.decompose()

    # 识别并分类核心 Section
    sections = soup.find_all('section', class_='ltx_section')
    intro_parts = []
    method_parts = []
    exp_parts = []
    limitation_parts = []

    for s in sections:
        h = s.find(['h2', 'h3', 'h4'])
        title_lower = (h.get_text(strip=True) if h else "").lower()
        text = clean_text(s.get_text())

        if any(k in title_lower for k in ["intro", "overview"]):
            intro_parts.append(text)
        elif any(k in title_lower for k in ["experiment", "evaluat", "result", "benchmark", "ablation"]):
            exp_parts.append(text)
        elif any(k in title_lower for k in ["limitation", "discussion", "future work", "conclusion"]):
            limitation_parts.append(text)
        elif "related work" in title_lower:
            continue  # 跳过单纯的 Related work
        else:
            # 核心方法与架构部分 (包括Preliminaries及以方法名命名的章节)
            method_parts.append(text)

    # 组装高密度正文（限制最大字符量以适配大模型上下文）
    intro_text = " ".join(intro_parts)[:4000]
    method_text = " ".join(method_parts)[:8500]
    exp_text = " ".join(exp_parts)[:5000]
    limitation_text = " ".join(limitation_parts)[:2500]

    has_content = bool(method_text or exp_text)

    return {
        "has_full_text": has_content,
        "github_urls": list(filtered_gh),
        "intro": intro_text,
        "method": method_text,
        "experiments": exp_text,
        "limitations": limitation_text,
        "html_url": f"https://arxiv.org/html/{clean_id}"
    }
