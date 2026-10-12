"""
World News 状态持久化与资讯去重记录模块
负责已分析资讯的历史留痕与精准去重 (URL 规范化清洗 + 标题匹配)
"""

import json
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from world_news.config import MEMORY_FILE, get_now_bjt

__all__ = ["WorldNewsMemory", "normalize_news_url"]

# 常见分析追踪与营销参数黑名单 (去重时需剥离)
TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "mod",
    "at_medium",
    "at_campaign",
    "ref",
    "ocid",
    "fbclid",
    "gclid",
    "cmpid",
}


def normalize_news_url(url: str) -> str:
    """
    标准化资讯 URL，剥离无意义的分析追踪参数 (utm、mod 等)，保留核心身份参数 (如 HN item?id=...)
    """
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
        query_pairs = parse_qsl(parts.query, keep_blank_values=False)
        clean_pairs = [(k, v) for k, v in query_pairs if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")]
        clean_query = urlencode(clean_pairs)
        path = parts.path.rstrip("/")
        normalized = urlunsplit(
            (
                parts.scheme.lower(),
                parts.netloc.lower(),
                path,
                clean_query,
                "",  # 剥离网页锚点
            )
        )
        return normalized.rstrip("/")
    except Exception:
        return url.strip().rstrip("/")


class WorldNewsMemory:
    """持久化状态记录库 (新闻去重与历史记录)"""

    def __init__(self, filepath: Path = MEMORY_FILE):
        self.filepath = filepath
        self.data = self._load()
        # 维护内存 set 以支持 O(1) 瞬时查询
        self._seen_urls = set(self.data.get("seen_urls", []))
        self._seen_titles = set(self.data.get("seen_titles", []))

    def _load(self) -> dict:
        if self.filepath.exists():
            try:
                with self.filepath.open(encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[World News] 读取状态记录异常，初始化默认记录: {e}", file=sys.stderr)
        return {
            "seen_urls": [],
            "seen_titles": [],
            "total_processed": 0,
            "last_run": None,
        }

    def is_seen(self, url: str = "", title: str = "") -> bool:
        """检查 URL 或标题是否已在历史记录中处理过"""
        if url:
            norm_url = normalize_news_url(url)
            if norm_url and norm_url in self._seen_urls:
                return True
        if title:
            norm_title = title.strip().lower()
            if norm_title and norm_title in self._seen_titles:
                return True
        return False

    def mark_seen(self, url: str = "", title: str = "") -> None:
        """标记资讯为已处理，同步更新内存缓存与待持久化数据"""
        added = False
        if url:
            norm_url = normalize_news_url(url)
            if norm_url and norm_url not in self._seen_urls:
                self._seen_urls.add(norm_url)
                self.data.setdefault("seen_urls", []).append(norm_url)
                added = True
        if title:
            norm_title = title.strip().lower()
            if norm_title and norm_title not in self._seen_titles:
                self._seen_titles.add(norm_title)
                self.data.setdefault("seen_titles", []).append(norm_title)
                added = True
        if added:
            self.data["total_processed"] = self.data.get("total_processed", 0) + 1

    def save(self, max_history: int = 5000) -> None:
        """持久化保存状态至 state/world-news/history.json，超限时自动修剪最早记录"""
        if len(self.data.get("seen_urls", [])) > max_history:
            self.data["seen_urls"] = self.data["seen_urls"][-max_history:]
            self._seen_urls = set(self.data["seen_urls"])
        if len(self.data.get("seen_titles", [])) > max_history:
            self.data["seen_titles"] = self.data["seen_titles"][-max_history:]
            self._seen_titles = set(self.data["seen_titles"])

        self.data["last_run"] = get_now_bjt().strftime("%Y-%m-%d %H:%M:%S")
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        with self.filepath.open("w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        print(f"[状态持久化] 记录已更新，累计处理资讯: {self.data.get('total_processed', 0)} 条 (当前库容: {len(self.data.get('seen_urls', []))} URLs)")
