"""
顶会官方 Workshops 审稿人招募雷达 (NIW 快速上岸通道)
监控 CVPR / ICCV / ECCV / NeurIPS 官方举办的 Workshops 开放招募
"""

from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from reviewer_radar.config import RECRUITMENT_KEYWORDS

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
}

# 顶会已接受的 Workshops 列表索引或历史/最新页面
WORKSHOP_INDEX_URLS = [
    {
        "conference": "CVPR",
        "url": "https://cvpr.thecvf.com/Conferences/2026/Workshops",
        "fallback_url": "https://cvpr.thecvf.com/Conferences/2025/Workshops",
    },
    {
        "conference": "ICCV",
        "url": "https://iccv.thecvf.com/Conferences/2025/Workshops",
    },
    {
        "conference": "ECCV",
        "url": "https://eccv2024.ecva.net/workshops",
    },
    {
        "conference": "NeurIPS",
        "url": "https://neurips.cc/Conferences/2025/Schedule?type=Workshop",
    },
]


def scan_top_workshops() -> list[dict]:
    """扫描顶会官方 Workshop 页面中开放审稿人招募的子专场"""
    workshop_opps = []
    print("🔬 [WorkshopRadar] 开始巡查顶会官方 Workshops 审稿人招募通道 (NIW 极佳过审捷径)...")

    for item in WORKSHOP_INDEX_URLS:
        conf = item["conference"]
        target_urls = [item["url"]]
        if "fallback_url" in item:
            target_urls.append(item["fallback_url"])

        for u in target_urls:
            try:
                resp = requests.get(u, headers=HEADERS, timeout=10)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                # 寻找 Workshop 列表链接
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    text = a.get_text(strip=True)
                    # 检查锚文本或父级段落中是否提及审稿人招募
                    combined = f"{text} {a.parent.get_text(strip=True) if a.parent else ''}".lower()
                    if any(kw in combined for kw in RECRUITMENT_KEYWORDS):
                        full_url = urljoin(u, href)
                        workshop_opps.append(
                            {
                                "conference": conf,
                                "full_name": f"{conf} Official Workshop",
                                "title": f"[{conf} Workshop] 审稿人招募: {text or 'Reviewer Call'}",
                                "source_url": u,
                                "form_url": full_url,
                                "context": combined[:300],
                                "type": "Top-Tier Workshop Reviewer Call (NIW Approved)",
                            }
                        )
            except Exception:
                continue

    return workshop_opps
