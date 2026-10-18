"""
Reviewer Radar 历史状态与持久化去重模块
管理 state/reviewer-radar/history.json，防止重复推送已知的审稿机会
"""

import json
from pathlib import Path
from typing import Any

from reviewer_radar.config import MEMORY_FILE


class RadarMemory:
    """管理已发送审稿招募/救火记录的持久化状态"""

    def __init__(self, memory_file: Path = MEMORY_FILE) -> None:
        self.memory_file = memory_file
        self.state: dict[str, Any] = {
            "notified_opportunities": {},  # key: opportunity_id (url or hash), value: {title, conference, timestamp}
            "last_run_bjt": None,
            "total_sent_count": 0,
        }
        self.load()

    def load(self) -> None:
        """从本地 JSON 文件加载历史状态"""
        if self.memory_file.exists():
            try:
                with open(self.memory_file, encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.state.update(data)
            except Exception as e:
                print(f"⚠️ [RadarMemory] 读取历史状态失败，将重置为空状态: {e}")

    def is_notified(self, opp_id: str) -> bool:
        """检查特定招募 ID / URL 是否已经通知过"""
        return opp_id in self.state.get("notified_opportunities", {})

    def record_notification(self, opp_id: str, info: dict[str, Any]) -> None:
        """记录已发送的招募通知"""
        if "notified_opportunities" not in self.state:
            self.state["notified_opportunities"] = {}
        self.state["notified_opportunities"][opp_id] = info
        self.state["total_sent_count"] = len(self.state["notified_opportunities"])

    def save(self, run_timestamp: str | None = None) -> None:
        """持久化保存至 state/reviewer-radar/history.json"""
        if run_timestamp:
            self.state["last_run_bjt"] = run_timestamp

        self.memory_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
            print(f"💾 [RadarMemory] 状态已保存至: {self.memory_file} (已记录 {len(self.state['notified_opportunities'])} 项)")
        except Exception as e:
            print(f"❌ [RadarMemory] 保存状态文件失败: {e}")
