"""
arXiv API 检索与候选论文解析模块 (基于官方 arxiv SDK)
"""

import re
import sys

import arxiv
from tenacity import retry, stop_after_attempt, wait_exponential


def clean_text(text: str) -> str:
    """清理多余空白字符"""
    return re.sub(r"\s+", " ", text).strip()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2.0, min=2.0, max=10.0), reraise=False)
def fetch_arxiv_candidates(track: dict, max_results: int = 12) -> list[dict]:
    """通过官方 arxiv SDK 获取候选论文并严格保持限流规范与重试机制"""
    client = arxiv.Client(page_size=max_results, delay_seconds=3.0, num_retries=3)
    search = arxiv.Search(query=track["query"], max_results=max_results, sort_by=arxiv.SortCriterion.SubmittedDate, sort_order=arxiv.SortOrder.Descending)

    papers = []
    try:
        for result in client.results(search):
            raw_id = result.get_short_id()
            clean_id = raw_id.split("v")[0] if "v" in raw_id else raw_id

            authors = [a.name for a in result.authors]
            author_str = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")
            published = result.published.strftime("%Y-%m-%d") if result.published else ""

            papers.append(
                {
                    "id": clean_id,
                    "title": clean_text(result.title),
                    "summary": clean_text(result.summary),
                    "authors": author_str,
                    "link": result.entry_id,
                    "pdf": result.pdf_url or f"https://arxiv.org/pdf/{clean_id}.pdf",
                    "html_url": f"https://arxiv.org/html/{clean_id}",
                    "published": published,
                }
            )
    except Exception as e:
        print(f"[arXiv SDK] 检索异常 ({track.get('tag', 'unknown')}): {e}", file=sys.stderr, flush=True)

    return papers
