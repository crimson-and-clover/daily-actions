"""
多源资讯与开源前沿数据抓取模块 (Feeds & Trending Fetcher)
包含针对网络波动的自适应重试机制 (HTTPAdapter + Retry)
"""

import html
import re
import sys
from datetime import UTC, datetime, timedelta

import feedparser
import requests
import trafilatura
from requests.adapters import HTTPAdapter
from tenacity import retry, stop_after_attempt, wait_exponential
from urllib3.util import Retry

from world_news.config import (
    DEFAULT_MAX_RETRIES,
    FETCH_TIMEOUT,
    GITHUB_SEARCH_DAYS,
    GITHUB_SEARCH_LIMIT,
    GITHUB_SEARCH_MIN_STARS,
    HN_TOP_STORIES_LIMIT,
    MACRO_SOURCES,
    RETRY_BACKOFF_FACTOR,
)


def create_retry_session(
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_factor: float = RETRY_BACKOFF_FACTOR,
    status_forcelist: tuple = (429, 500, 502, 503, 504),
) -> requests.Session:
    """创建内置指数退避重试能力的 requests Session"""
    session = requests.Session()
    retry_strategy = Retry(total=max_retries, backoff_factor=backoff_factor, status_forcelist=status_forcelist, allowed_methods=["HEAD", "GET", "OPTIONS"], raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1.5, min=1.0, max=8.0), reraise=True)
def get_with_retry(session: requests.Session, url: str, **kwargs) -> requests.Response:
    """基于 tenacity 指数退避的通用 HTTP GET 重试调用"""
    return session.get(url, **kwargs)


def clean_html(raw_html: str) -> str:
    """基于 trafilatura 与实体解码的高保真文本清洗"""
    if not raw_html:
        return ""
    if "<" in raw_html and ">" in raw_html:
        extracted = trafilatura.extract(raw_html)
        if extracted:
            return extracted.strip()
    cleanr = re.compile(r"<.*?>")
    return html.unescape(re.sub(cleanr, "", raw_html)).strip()


def fetch_macro_finance_feeds() -> list:
    """
    抓取宏观地缘与财经资本市场候选池：
    涵盖 BBC World、CNBC Markets、WSJ World，自带网络波动重试
    """
    items = []
    seen_titles = set()
    idx = 0
    session = create_retry_session()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

    for src in MACRO_SOURCES:
        try:
            resp = get_with_retry(session, src["url"], headers=headers, timeout=FETCH_TIMEOUT)
            if resp.status_code == 200:
                feed = feedparser.parse(resp.content)
            else:
                print(f"[警告] 抓取 {src['name']} 响应码非200 [HTTP {resp.status_code}]，尝试兜底解析", file=sys.stderr)
                feed = feedparser.parse(src["url"])

            count = 0
            for entry in feed.entries:
                title = clean_html(entry.title)
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)

                summary = clean_html(getattr(entry, "summary", ""))
                pub = getattr(entry, "published", "").split(" +")[0]
                items.append({"idx": idx, "source": src["name"], "title": title, "link": entry.link, "summary": summary, "published": pub})
                idx += 1
                count += 1
                if count >= src["limit"]:
                    break
        except Exception as e:
            print(f"[抓取异常] {src['name']}: {e}", file=sys.stderr)

    return items


def fetch_tech_opensource_feeds() -> list:
    """
    抓取科技与开源前沿候选池：
    涵盖 Hacker News Top 讨论 + GitHub 新晋高星爆发项目，支持连接容错与重试
    """
    items = []
    idx = 0
    session = create_retry_session()

    # 1. Hacker News Top Stories
    try:
        top_ids_url = "https://hacker-news.firebaseio.com/v0/topstories.json"
        resp = get_with_retry(session, top_ids_url, timeout=FETCH_TIMEOUT)
        if resp.status_code == 200:
            story_ids = resp.json()[:HN_TOP_STORIES_LIMIT]

            for s_id in story_ids:
                try:
                    item_url = f"https://hacker-news.firebaseio.com/v0/item/{s_id}.json"
                    item_resp = get_with_retry(session, item_url, timeout=FETCH_TIMEOUT)
                    if item_resp.status_code == 200:
                        d = item_resp.json()
                        title = clean_html(d.get("title", ""))
                        url = d.get("url", f"https://news.ycombinator.com/item?id={s_id}")
                        score = d.get("score", 0)
                        comments = d.get("descendants", 0)
                        items.append(
                            {
                                "idx": idx,
                                "type": "hn",
                                "source": "Hacker News",
                                "title": title,
                                "url": url,
                                "hn_url": f"https://news.ycombinator.com/item?id={s_id}",
                                "score": score,
                                "comments": comments,
                                "description": f"社区点赞: {score} | 评论数: {comments}",
                            }
                        )
                        idx += 1
                except Exception:
                    continue
        else:
            print(f"[警告] Hacker News Top 接口异常: HTTP {resp.status_code}", file=sys.stderr)
    except Exception as e:
        print(f"[抓取异常] Hacker News: {e}", file=sys.stderr)

    # 2. GitHub 近指定天数新建且快速爆发的高星新项目
    try:
        since_date = (datetime.now(UTC) - timedelta(days=GITHUB_SEARCH_DAYS)).strftime("%Y-%m-%d")
        gh_url = f"https://api.github.com/search/repositories?q=created:>{since_date}+stars:>{GITHUB_SEARCH_MIN_STARS}&sort=stars&order=desc&per_page={GITHUB_SEARCH_LIMIT}"
        headers = {"User-Agent": "daily-actions-agent", "Accept": "application/vnd.github.v3+json"}
        gh_resp = get_with_retry(session, gh_url, headers=headers, timeout=FETCH_TIMEOUT)
        if gh_resp.status_code == 200:
            repos = gh_resp.json().get("items", [])
            for r in repos:
                full_name = r.get("full_name", "")
                desc = clean_html(r.get("description", "") or "暂无官方描述")
                stars = r.get("stargazers_count", 0)
                lang = r.get("language", "Unknown")
                html_url = r.get("html_url", "")

                items.append(
                    {
                        "idx": idx,
                        "type": "github",
                        "source": "GitHub Trending",
                        "title": f"[开源新星] {full_name} (语言: {lang} | ★{stars})",
                        "url": html_url,
                        "hn_url": html_url,
                        "score": stars,
                        "comments": r.get("forks_count", 0),
                        "description": f"核心描述: {desc} (语言: {lang}, Stars: {stars})",
                    }
                )
                idx += 1
        else:
            print(f"[警告] GitHub API 接口响应异常: HTTP {gh_resp.status_code}", file=sys.stderr)
    except Exception as e:
        print(f"[抓取异常] GitHub Trending: {e}", file=sys.stderr)

    return items
