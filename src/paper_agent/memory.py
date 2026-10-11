"""
Paper Agent 状态持久化与去重记录模块
"""

import json
import sys
from pathlib import Path

from paper_agent.config import MEMORY_FILE, get_now_bjt


class AgentMemory:
    """持久化状态记录库"""

    def __init__(self, filepath: Path = MEMORY_FILE):
        self.filepath = filepath
        self.data = self._load()

    def _load(self):
        if self.filepath.exists():
            try:
                with self.filepath.open(encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"读取状态记录异常，初始化默认记录: {e}", file=sys.stderr)
        return {"seen_paper_ids": [], "total_analyzed": 0, "last_run": None}

    def is_seen(self, arxiv_id: str) -> bool:
        return arxiv_id in self.data.get("seen_paper_ids", [])

    def mark_seen(self, arxiv_id: str):
        if "seen_paper_ids" not in self.data:
            self.data["seen_paper_ids"] = []
        if arxiv_id not in self.data["seen_paper_ids"]:
            self.data["seen_paper_ids"].append(arxiv_id)
            self.data["total_analyzed"] = self.data.get("total_analyzed", 0) + 1

    def save(self):
        self.data["last_run"] = get_now_bjt().strftime("%Y-%m-%d %H:%M:%S")
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        with self.filepath.open("w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        print(f"[状态持久化] 记录已更新，累计分析文献: {self.data.get('total_analyzed', 0)} 篇")
