import json
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from inbox_agent.config import INBOX_STATE_KEY, IS_CI, MEMORY_FILE, get_now_bjt


class InboxMemory:
    """长期状态记录器：记录已分类邮件 ID 与日程池，使用 Fernet (AES-128-CBC + HMAC) 密文持久化"""

    def __init__(self, filepath: Path = MEMORY_FILE):
        self.filepath = filepath
        self.key = INBOX_STATE_KEY
        self.fernet = None
        if self.key:
            try:
                self.fernet = Fernet(self.key.encode())
            except Exception as e:
                print(f"[Memory Security Error] 非法的 INBOX_STATE_KEY 格式: {e}", file=sys.stderr)
                if IS_CI:
                    sys.exit(1)
        else:
            if IS_CI:
                print("[Fatal Security Error] CI 环境中必须配置 INBOX_STATE_KEY Secrets！严禁明文运行！", file=sys.stderr)
                sys.exit(1)
            else:
                print("[Security Warning] 未检测到 INBOX_STATE_KEY，请运行 `uv run python scripts/generate_inbox_key.py` 生成密钥配置到 .env！", file=sys.stderr)

        self.data = {
            "processed_message_ids": [],
            "history_processed_ids": [],
            "spam_message_ids": [],
            "last_run": "",
            "total_processed": 0,
            "total_spam_filtered": 0,
            "total_pruned_90d": 0,
            "active_schedules": [],
        }
        self.load()

    def load(self):
        if not self.filepath.exists():
            return

        if not self.fernet:
            print(f"[Memory Warning] 缺少解密密钥 INBOX_STATE_KEY，无法读取加密状态文件: {self.filepath}", file=sys.stderr)
            if IS_CI:
                sys.exit(1)
            return

        try:
            encrypted_bytes = self.filepath.read_bytes()
            if not encrypted_bytes:
                return
            decrypted_bytes = self.fernet.decrypt(encrypted_bytes)
            content = json.loads(decrypted_bytes.decode("utf-8"))
            self.data.update(content)
            print(f"[Memory Loaded] 加密状态已成功解密加载 ({len(self.data.get('processed_message_ids', []))} 封日常历史, {len(self.data.get('history_processed_ids', []))} 封积压历史已处理, {len(self.data.get('active_schedules', []))} 条待办日程)")
        except InvalidToken:
            print("[Memory Security Error] 解密失败：INBOX_STATE_KEY 密钥不匹配或数据已被篡改！", file=sys.stderr)
            if IS_CI:
                sys.exit(1)
        except Exception as e:
            print(f"[Memory Error] 加载状态失败: {e}，将初始化全新状态", file=sys.stderr)
            if IS_CI:
                sys.exit(1)

    def is_processed(self, message_id: str) -> bool:
        """主日常 CI 专用：判断该邮件是否已被日常收件箱助手处理过"""
        if not message_id:
            return False
        return message_id in self.data.get("processed_message_ids", [])

    def is_history_processed(self, message_id: str) -> bool:
        """历史 CI 专用：判断该 90 天以上历史邮件是否已被 History Agent 研判处理过"""
        if not message_id:
            return False
        return message_id in self.data.get("history_processed_ids", [])

    def is_confirmed_spam(self, message_id: str) -> bool:
        """检查该邮件是否已被主 Agent 确认为垃圾邮件 (Spam)"""
        if not message_id:
            return False
        return message_id in self.data.get("spam_message_ids", [])

    def mark_processed(self, message_id: str, is_spam: bool = False):
        """主日常 CI 记录邮件处理状态"""
        if not message_id:
            return
        if "processed_message_ids" not in self.data:
            self.data["processed_message_ids"] = []
        if "spam_message_ids" not in self.data:
            self.data["spam_message_ids"] = []

        if message_id not in self.data["processed_message_ids"]:
            self.data["processed_message_ids"].append(message_id)
            if len(self.data["processed_message_ids"]) > 5000:
                self.data["processed_message_ids"] = self.data["processed_message_ids"][-4000:]
            self.data["total_processed"] = self.data.get("total_processed", 0) + 1

        if is_spam:
            if message_id not in self.data["spam_message_ids"]:
                self.data["spam_message_ids"].append(message_id)
                if len(self.data["spam_message_ids"]) > 3000:
                    self.data["spam_message_ids"] = self.data["spam_message_ids"][-2000:]
            self.data["total_spam_filtered"] = self.data.get("total_spam_filtered", 0) + 1

    def mark_history_processed(self, message_id: str):
        """历史 CI 专用：标记该历史邮件已被 History Agent 研判处置"""
        if not message_id:
            return
        if "history_processed_ids" not in self.data:
            self.data["history_processed_ids"] = []

        if message_id not in self.data["history_processed_ids"]:
            self.data["history_processed_ids"].append(message_id)
            if len(self.data["history_processed_ids"]) > 5000:
                self.data["history_processed_ids"] = self.data["history_processed_ids"][-4000:]

    def record_pruned(self, count: int):
        self.data["total_pruned_90d"] = self.data.get("total_pruned_90d", 0) + count

    def add_schedule(self, schedule_item: dict):
        """将包含具体日期 (event_date) 的日程及提前预警天数 (advance_days) 持久化保存到待办日历池中"""
        event_date = (schedule_item.get("event_date") or "").strip()
        if not event_date:
            return
        if "active_schedules" not in self.data:
            self.data["active_schedules"] = []

        # 检查是否已有相同 message_id 或相同主题和时间的日程
        msg_id = schedule_item.get("message_id")
        for existing in self.data["active_schedules"]:
            if msg_id and existing.get("message_id") == msg_id:
                return
            if existing.get("subject") == schedule_item.get("subject") and existing.get("event_date") == event_date:
                return

        self.data["active_schedules"].append(
            {
                "message_id": msg_id,
                "subject": schedule_item.get("subject", ""),
                "from": schedule_item.get("from", ""),
                "tldr": schedule_item.get("tldr", ""),
                "action_items": schedule_item.get("action_items", []),
                "event_time": schedule_item.get("event_time", ""),
                "event_date": event_date,
                "advance_days": schedule_item.get("advance_days", 3),
                "priority": schedule_item.get("priority", "P1"),
                "added_at": get_now_bjt().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

    def get_due_schedules(self, today_str: str) -> list[dict]:
        """
        获取当前需要提醒的日程列表：
        包含：
        1. 今天到期 (days_left == 0)
        2. 未来到期但已进入 AI 决定的提前预警窗口期 (0 < days_left <= advance_days)
        3. 轻微逾期（逾期 1~2 天内未办理完）
        """
        if "active_schedules" not in self.data:
            return []
        from datetime import datetime

        dt_today = datetime.strptime(today_str, "%Y-%m-%d")

        due_list = []
        for item in self.data["active_schedules"]:
            ev_date = (item.get("event_date") or "").strip()
            if not ev_date:
                continue
            try:
                dt_ev = datetime.strptime(ev_date, "%Y-%m-%d")
                delta_days = (dt_ev - dt_today).days
                advance = int(item.get("advance_days", 3))

                # 判断是否应当进入提醒视图
                if delta_days == 0:
                    item_copy = dict(item)
                    item_copy["due_status"] = "今天到期"
                    item_copy["days_left"] = 0
                    due_list.append(item_copy)
                elif 0 < delta_days <= advance:
                    item_copy = dict(item)
                    item_copy["due_status"] = f"还剩 {delta_days} 天"
                    item_copy["days_left"] = delta_days
                    due_list.append(item_copy)
                elif -2 <= delta_days < 0:
                    item_copy = dict(item)
                    item_copy["due_status"] = f"已逾期 {abs(delta_days)} 天"
                    item_copy["days_left"] = delta_days
                    due_list.append(item_copy)
            except (ValueError, TypeError):
                continue

        # 按剩余天数升序排序（最紧迫的排在最前）
        due_list.sort(key=lambda x: x.get("days_left", 999))
        return due_list

    def prune_expired_schedules(self, today_str: str):
        """清理已过期超过 3 天的历史日程"""
        if "active_schedules" not in self.data:
            return
        retained = []
        for item in self.data["active_schedules"]:
            ev_date = item.get("event_date", "")
            # 保留未来的或最近 3 天内的
            if not ev_date or ev_date >= today_str:
                retained.append(item)
            else:
                # 简单日期比较保留 3 天
                try:
                    from datetime import datetime

                    dt_ev = datetime.strptime(ev_date, "%Y-%m-%d")
                    dt_now = datetime.strptime(today_str, "%Y-%m-%d")
                    if (dt_now - dt_ev).days <= 3:
                        retained.append(item)
                except (ValueError, TypeError):
                    pass
        self.data["active_schedules"] = retained

    def save(self):
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self.data["last_run"] = get_now_bjt().strftime("%Y-%m-%d %H:%M:%S")

        if not self.fernet:
            print("[Memory Security Error] 缺少 INBOX_STATE_KEY，严禁向磁盘保存未加密的状态数据！", file=sys.stderr)
            if IS_CI:
                sys.exit(1)
            return

        try:
            json_str = json.dumps(self.data, ensure_ascii=False, indent=2)
            encrypted_bytes = self.fernet.encrypt(json_str.encode("utf-8"))
            self.filepath.write_bytes(encrypted_bytes)
            print(f"[Memory Saved] 状态已成功进行 Fernet AES 对称加密并保存至: {self.filepath}")

            # 确保工作目录下无残留的明文 history.json
            legacy_json = self.filepath.parent / "history.json"
            if legacy_json.exists():
                try:
                    legacy_json.unlink()
                except Exception:
                    pass
        except Exception as e:
            print(f"[Memory Error] 加密保存状态文件失败: {e}", file=sys.stderr)
            if IS_CI:
                sys.exit(1)
