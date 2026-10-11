"""
arXiv HTML 论文全文高保真解析器
通过 arXiv 官方 HTML 版本 (https://arxiv.org/html/{id}) 或 ar5iv 实验室版本，
提取结构化的正文章节（Introduction, Method/Architecture, Experiments, Limitations）
并过滤掉 References 与致谢等冗余噪点。
"""

import re
import sys
import urllib.parse

import bs4
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1.5, min=1.0, max=8.0), reraise=False)
def _fetch_url_with_retry(url: str) -> requests.Response | None:
    """带指数退避重试的单页面抓取函数"""
    r = requests.get(url, headers=HEADERS, timeout=20)
    if r.status_code == 200:
        return r
    return None


def clean_text(text: str) -> str:
    """清理多余空白与换行"""
    return re.sub(r"\s+", " ", text).strip()


def extract_figures_from_soup(soup: bs4.BeautifulSoup, base_url: str) -> list[dict]:
    """
    从 arXiv HTML 全文中提取论文主图与方法架构图 (Key Figures)。
    优先识别图题包含 overview, architecture, framework, pipeline, method, workflow 的核心图。
    最多保留 2 张代表性关键图像。
    """
    raw_figures = soup.find_all("figure", class_="ltx_figure")
    top_figs = [f for f in raw_figures if not f.find_parent("figure", class_="ltx_figure")]

    extracted = []
    for f in top_figs:
        cap_el = f.find("figcaption", recursive=False)
        cap_text = ""
        if cap_el:
            cap_text = clean_text(cap_el.get_text(separator=" ", strip=True))

        imgs = []
        for img in f.find_all("img"):
            src = img.get("src")
            if src and not src.startswith(("data:", "javascript:")):
                u = urllib.parse.urljoin(base_url, src)
                if u not in imgs:
                    imgs.append(u)
        for obj in f.find_all("object"):
            data = obj.get("data")
            if data and not data.startswith(("data:", "javascript:")):
                u = urllib.parse.urljoin(base_url, data)
                if u not in imgs:
                    imgs.append(u)

        if imgs:
            extracted.append({"caption": cap_text, "images": imgs})

    if not extracted:
        return []

    # 智能选择主图 (Main/Teaser) 和 方法/架构图 (Architecture/Framework)
    method_keywords = ["overview", "architecture", "framework", "pipeline", "method", "workflow", "model", "approach", "structure"]
    selected = []

    # 1. 寻找主图 / 第一张图
    fig1 = None
    for idx, fig in enumerate(extracted):
        cap_lower = fig["caption"].lower()
        if idx == 0 or re.search(r"\bfig(ure)?\.?\s*1\b", cap_lower):
            fig1 = fig
            break
    if not fig1 and extracted:
        fig1 = extracted[0]

    selected.append(fig1)

    # 2. 寻找方法/架构图 (排除已被选中的图)
    for fig in extracted:
        if fig is fig1:
            continue
        cap_lower = fig["caption"].lower()
        if any(k in cap_lower for k in method_keywords):
            selected.append(fig)
            break

    # 如果只有一张图但还有其它图，最多凑满两张（通常第二张也很有代表性）
    if len(selected) < 2 and len(extracted) > 1:
        for fig in extracted:
            if fig not in selected:
                selected.append(fig)
                break

    return selected[:2]


def extract_official_github_repo(soup: bs4.BeautifulSoup, title_text: str = "", affiliations_text: str = "") -> list[str]:
    """
    智能提取论文官方核心开源仓库，并进行有效性校验（过滤伪开源、404 与非官方依赖库）：
    1. 仅排除基础页面设施 (arXiv / LaTeXML / GitHub Actions)，绝不粗暴屏蔽机构组织 (如 Meta/Google/OpenAI)；
    2. 解析全部 <a> 标签与正文文本中的 GitHub 链接及归一化仓库路径；
    3. 基于作者第一人称发布词 (our code/model/repo, released at 等)、论文标题匹配度、作者机构匹配度进行精细加权；
    4. 对显式第三方引用 (combines from, see https, baseline) 进行合理降权；
    5. 发送轻量 HTTP 请求核验仓库是否为存活的公开仓库 (HTTP 200)，过滤 404 伪开源；
    6. 最终仅保留 1 个最高置信度的有效主开源仓库。
    """
    # 仅屏蔽 arXiv 页面自带的渲染基础设施和反馈组件，保留所有科研机构和作者账号
    infra_orgs = {"arxiv", "brucemiller", "actions"}

    title_words = set(re.findall(r"\b[a-zA-Z]{3,}\b", title_text.lower())) if title_text else set()
    affil_lower = affiliations_text.lower() if affiliations_text else ""

    found_entries = []
    # 1. 扫描 <a> 标签
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "github.com" in href:
            anchor_text = a.get_text().strip()
            parent = a.find_parent(["p", "span", "div", "li"])
            p_text = parent.get_text().strip() if parent else ""
            found_entries.append((href, anchor_text, p_text))

    # 2. 扫描纯文本中出现的链接
    for el in soup.find_all(["p", "span", "li"]):
        txt = el.get_text()
        if "github.com/" in txt:
            matches = re.findall(r"https?://github\.com/[a-zA-Z0-9_\-\./]+", txt)
            for m in matches:
                found_entries.append((m, "", txt))

    candidates: dict[str, int] = {}
    for raw_url, anchor_text, context in found_entries:
        parsed = urllib.parse.urlparse(raw_url)
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if len(parts) < 2:
            continue
        org, repo = parts[0], parts[1].rstrip(".")
        if org.lower() in infra_orgs or repo.lower().endswith((".png", ".jpg", ".svg", ".gif", ".zip", ".tar", ".pdf")):
            continue

        clean_url = f"https://github.com/{org}/{repo}"
        ctx_lower = context.lower()
        anchor_lower = anchor_text.lower()
        score = 0

        # 第一人称或作者官方声明词 (+15)
        release_signals = [
            "our code",
            "our model",
            "our data",
            "our checkpoint",
            "our implementation",
            "our repository",
            "our github",
            "we release",
            "we open-source",
            "code is available at",
            "code available at",
            "source code is available",
            "official implementation",
            "inference code at",
            "github repository here",
            "released at https://github",
            "provided at https://github",
            "available at https://github",
        ]
        if any(s in ctx_lower or s in anchor_lower for s in release_signals):
            score += 15

        # 锚文本本身是指向代码仓库 (+5)
        if any(w in anchor_lower for w in ["code", "github", "repository", "repo", "here"]):
            score += 5

        # 论文标题相关度加成 (repo 名字与论文标题包含相同专有名词，如 Llama, BlackMamba, Beacon) (+8)
        repo_words = set(re.findall(r"\b[a-zA-Z]{3,}\b", repo.lower()))
        org_words = set(re.findall(r"\b[a-zA-Z]{3,}\b", org.lower()))
        if title_words and (repo_words & title_words or org_words & title_words):
            score += 8

        # 机构相关度加成 (若 github 组织名与作者 Affiliation 一致，如 meta-llama / Meta) (+8)
        if affil_lower and any(w in affil_lower for w in [org.lower()]):
            score += 8

        # 降权项：若语境明确属于引用第三方基线或已有公开分词器/数据集 (-10)
        third_party_signals = ["combines 100k tokens from", "see https://github", "adapted from", "reproduced with", "comparing with the ground truth"]
        if any(s in ctx_lower for s in third_party_signals) and score <= 5:
            score -= 10

        candidates[clean_url] = max(candidates.get(clean_url, 0), score)

    if not candidates:
        return []

    # 按置信度得分降序排列
    sorted_candidates = sorted(candidates.items(), key=lambda x: x[1], reverse=True)

    # 实时网络核验：检测是否为 404 伪开源或已注销仓库
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    for candidate_url, score in sorted_candidates[:3]:
        # 仅当置信度高于基础门槛时才发起探活请求
        if score < 5:
            continue
        try:
            r = requests.get(candidate_url, headers=headers, timeout=4, stream=True)
            if r.status_code == 200:
                # 校验成功且存活，只保留置信度最高的唯一官方主仓库
                return [candidate_url]
            else:
                print(f"     [假开源过滤] 仓库无法访问 (HTTP {r.status_code}): {candidate_url}", file=sys.stderr, flush=True)
        except Exception:
            continue

    return []


def extract_full_paper(arxiv_id: str) -> dict:
    """
    抓取并解析 arXiv 论文 HTML 全文。
    返回结构化的章节正文、项目 GitHub 链接以及核心主图/架构图。
    """
    clean_id = arxiv_id.strip()
    if clean_id.startswith("http"):
        clean_id = clean_id.split("/abs/")[-1].split("/html/")[-1]

    urls_to_try = [f"https://arxiv.org/html/{clean_id}", f"https://ar5iv.labs.arxiv.org/html/{clean_id}"]

    resp = None
    matched_url = f"https://arxiv.org/html/{clean_id}"
    for url in urls_to_try:
        r = _fetch_url_with_retry(url)
        if r and ("ltx_document" in r.text or "ltx_page_main" in r.text):
            resp = r
            matched_url = url
            break

    if not resp:
        return {"has_full_text": False, "github_urls": [], "figures": [], "intro": "", "method": "", "experiments": "", "limitations": "", "html_url": f"https://arxiv.org/html/{clean_id}"}

    soup = bs4.BeautifulSoup(resp.text, "html.parser")

    # 提取核心主图与方法图 (在剔除元素之前提取，确保完整性)
    key_figures = extract_figures_from_soup(soup, matched_url)

    # 提取标题与作者所属实验室/机构信息
    title_text = ""
    title_el = soup.find(class_="ltx_title")
    if title_el:
        title_text = clean_text(title_el.get_text(separator=" ", strip=True))

    affiliations_text = ""
    authors_div = soup.find(class_="ltx_authors")
    if authors_div:
        affiliations_text = clean_text(authors_div.get_text(separator=" ", strip=True))[:1200]

    # 剔除 References、致谢、页眉页脚与版权声明噪声
    for elem in soup.find_all(["footer", "header", "nav", "aside", "section", "div", "span", "li"], class_=["ltx_bibliography", "ltx_role_ref", "ltx_copyright", "ltx_page_footer", "ds-site-footer", "ds-site-header"]):
        elem.decompose()

    # 智能提取并核验唯一的官方有效 GitHub 仓库（过滤 404 与非官方库）
    official_gh_urls = extract_official_github_repo(soup, title_text=title_text, affiliations_text=affiliations_text)

    # 识别并分类核心 Section
    sections = soup.find_all("section", class_="ltx_section")
    intro_parts = []
    method_parts = []
    exp_parts = []
    limitation_parts = []

    for s in sections:
        h = s.find(["h2", "h3", "h4"])
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
        "github_urls": official_gh_urls,
        "figures": key_figures,
        "affiliations": affiliations_text,
        "intro": intro_text,
        "method": method_text,
        "experiments": exp_text,
        "limitations": limitation_text,
        "html_url": f"https://arxiv.org/html/{clean_id}",
    }
