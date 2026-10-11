"""
Market FX 状态持久化与历史快照存储模块
对标 Paper Agent 的 AgentMemory 设计，持久化存储于 state/market-fx 分支
"""

import json
import sys
from pathlib import Path

from market_fx.config import MEMORY_DIR, MEMORY_FILE, get_now_bjt


class MarketMemory:
    """持久化状态与行情快照记录库"""

    def __init__(self, filepath: Path = MEMORY_FILE, memory_dir: Path = MEMORY_DIR):
        self.filepath = filepath
        self.memory_dir = memory_dir
        self.data = self._load()

    def _load(self) -> dict:
        if self.filepath.exists():
            try:
                with self.filepath.open(encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[状态记录] 读取历史异常，初始化默认记录: {e}", file=sys.stderr, flush=True)
        return {"last_run": None, "total_runs": 0, "daily_snapshots": {}}

    def record_snapshot(self, date_str: str, snapshot: dict):
        """记录当日核心行情与量化指标快照"""
        if "daily_snapshots" not in self.data:
            self.data["daily_snapshots"] = {}

        self.data["daily_snapshots"][date_str] = snapshot
        self.data["total_runs"] = self.data.get("total_runs", 0) + 1
        self.data["last_run"] = get_now_bjt().strftime("%Y-%m-%d %H:%M:%S")

    def save(self):
        """保存状态至 JSON 文件"""
        try:
            self.memory_dir.mkdir(parents=True, exist_ok=True)
            with self.filepath.open("w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            days_count = len(self.data.get("daily_snapshots", {}))
            print(f"✅ [状态持久化] 历史快照已更新至: {self.filepath} (累计记录 {days_count} 天)", flush=True)
        except Exception as e:
            print(f"⚠️ [状态持久化] 保存失败: {e}", file=sys.stderr, flush=True)
