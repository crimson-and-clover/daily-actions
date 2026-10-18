"""
各大顶级会议官网爬虫与审稿人招募表单嗅探器
覆盖 CVPR, ICCV, ECCV, NeurIPS, ICLR, ICML, AAAI 官方主页与公告栏
"""

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from reviewer_radar.config import FORM_DOMAINS, RECRUITMENT_KEYWORDS, TARGET_CONFERENCES

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def is_form_link(url: str) -> bool:
    """判断链接是否指向外部表单平台 (Google Forms, MS Forms, OpenReview Form)"""
    url_lower = url.lower()
    return any(domain in url_lower for domain in FORM_DOMAINS)


def match_reviewer_keywords(text: str) -> bool:
    """判断文本是否包含审稿人招募/救火关键词"""
    text_lower = text.lower()
    return any(kw in text_lower for kw in RECRUITMENT_KEYWORDS)


def fetch_conference_opportunities(conf: dict) -> list[dict]:
    """爬取并分析单个会议官网的审稿招募线索"""
    opportunities = []
    base_url = conf["official_url"]
    short_name = conf["short_name"]

    urls_to_check = [base_url]

    # 针对 CVPR/ICCV 的常见子路径
    if short_name in ["CVPR", "ICCV"]:
        for year in [2025, 2026, 2027]:
            urls_to_check.extend(
                [
                    f"{base_url}/Conferences/{year}",
                    f"{base_url}/Conferences/{year}/CallForReviewers",
                    f"{base_url}/Conferences/{year}/ForReviewers",
                ]
            )
    elif short_name == "NeurIPS":
        urls_to_check.extend(
            [
                "https://neurips.cc/Conferences/2025/CallForReviewers",
                "https://neurips.cc/Conferences/2026/CallForReviewers",
            ]
        )
    elif short_name == "ICLR":
        urls_to_check.extend(
            [
                "https://iclr.cc/Conferences/2026/CallForReviewers",
            ]
        )

    visited = set()

    for target_url in urls_to_check:
        if target_url in visited:
            continue
        visited.add(target_url)

        try:
            resp = requests.get(target_url, headers=HEADERS, timeout=12)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            page_text = soup.get_text(separator=" ", strip=True)

            # 1. 查找所有可能指向招募表单的链接
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].strip()
                full_link = urljoin(target_url, href)
                anchor_text = a_tag.get_text(strip=True)
                parent_text = a_tag.parent.get_text(strip=True) if a_tag.parent else ""

                combined_context = f"{anchor_text} {parent_text}"

                # 场景 A: 直连 Google/MS Forms，且上下文提到 Reviewer
                if is_form_link(full_link) and match_reviewer_keywords(combined_context):
                    opportunities.append(
                        {
                            "conference": short_name,
                            "full_name": conf["full_name"],
                            "title": f"[{short_name}] 审稿人申请表单: {anchor_text or 'Application Form'}",
                            "source_url": target_url,
                            "form_url": full_link,
                            "context": combined_context[:400],
                            "type": "Emergency/Volunteer Reviewer Form",
                        }
                    )

                # 场景 B: 站内链接明确包含 Call for Reviewers
                elif match_reviewer_keywords(anchor_text) and not is_form_link(full_link):
                    # 发现专属审稿页面，进一步抓取该子页面
                    sub_opp = _check_sub_reviewer_page(short_name, conf["full_name"], full_link, anchor_text)
                    if sub_opp:
                        opportunities.append(sub_opp)

            # 2. 检查页面正文是否有紧急救火/招募段落
            emergency_matches = re.findall(
                r"(?:emergency|volunteer)\s+reviewer[s]?.*?(?:https?://[^\s\"'>]+)",
                page_text,
                re.IGNORECASE,
            )
            for match in emergency_matches:
                urls = re.findall(r"https?://[^\s\"'>]+", match)
                if urls:
                    form_url = urls[0]
                    opportunities.append(
                        {
                            "conference": short_name,
                            "full_name": conf["full_name"],
                            "title": f"[{short_name}] 官网紧急审稿人招募公告",
                            "source_url": target_url,
                            "form_url": form_url,
                            "context": match[:400],
                            "type": "Emergency Reviewer Notice",
                        }
                    )

        except Exception:
            # 网站不可达时静默忽略，保证其余会议正常抓取
            continue

    return opportunities


def _check_sub_reviewer_page(conf_name: str, full_name: str, url: str, link_text: str) -> dict | None:
    """深入分析子审稿页，提取具体的申请表单链接"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            if is_form_link(href):
                return {
                    "conference": conf_name,
                    "full_name": full_name,
                    "title": f"[{conf_name}] 审稿人招募页面与表单: {link_text}",
                    "source_url": url,
                    "form_url": href,
                    "context": a_tag.parent.get_text(strip=True)[:400] if a_tag.parent else link_text,
                    "type": "Official Call for Reviewers",
                }
    except Exception:
        return None
    return None


def scan_all_conference_websites() -> list[dict]:
    """并发/顺序扫描全部 7 大顶会官网"""
    all_opps = []
    print("🌐 [WebCrawler] 开始巡查各大顶会官网 (CVPR/ICCV/ECCV/NeurIPS/ICLR/ICML/AAAI)...")
    for conf in TARGET_CONFERENCES:
        opps = fetch_conference_opportunities(conf)
        if opps:
            print(f"  ✨ 在 {conf['short_name']} 发现 {len(opps)} 个潜在审稿招募线索！")
            all_opps.extend(opps)
    return all_opps
