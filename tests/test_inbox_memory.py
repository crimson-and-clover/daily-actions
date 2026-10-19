import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from inbox_agent.memory import (
    HistoryMemory,
    HistoryStateData,
    InboxMemory,
    InboxStateData,
)


class TestInboxMemory(unittest.TestCase):
    def setUp(self):
        self.key = Fernet.generate_key().decode()

    def test_inbox_memory_crud_and_encryption(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            inbox_file = tmp_path / "inbox.enc"

            # 1. 初始化空内存
            inbox_mem = InboxMemory(filepath=inbox_file, key=self.key)
            self.assertIsInstance(inbox_mem.data, InboxStateData)
            self.assertEqual(inbox_mem.data.version, 1)
            self.assertFalse(inbox_mem.is_processed("msg-1"))

            # 2. 标记处理与垃圾邮件过滤
            inbox_mem.mark_processed("msg-1", is_spam=False)
            inbox_mem.mark_processed("msg-2", is_spam=True)
            self.assertTrue(inbox_mem.is_processed("msg-1"))
            self.assertTrue(inbox_mem.is_confirmed_spam("msg-2"))
            self.assertFalse(inbox_mem.is_confirmed_spam("msg-1"))

            # 3. 添加日程（含时区、自动生成 schedule_id、覆盖更新）
            item1 = {
                "message_id": "<flight-123@airline.com>",
                "title": "东京羽田航班",
                "from": "service@airline.com",
                "event_date": "2026-10-25",
                "timezone": "Asia/Tokyo",
                "advance_days": 3,
                "priority": "P1",
            }
            inbox_mem.add_schedule(item1)
            schedules = inbox_mem.get_active_schedules()
            self.assertEqual(len(schedules), 1)
            sched_id = schedules[0]["schedule_id"]
            self.assertTrue(len(sched_id) > 0)
            self.assertEqual(schedules[0]["timezone"], "Asia/Tokyo")

            # 更新相同 message_id 的日程
            item1_updated = {
                "message_id": "<flight-123@airline.com>",
                "title": "东京羽田航班(改签)",
                "event_date": "2026-10-26",
                "timezone": "Asia/Tokyo",
                "advance_days": 2,
            }
            inbox_mem.add_schedule(item1_updated)
            active = inbox_mem.get_active_schedules()
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["schedule_id"], sched_id)  # schedule_id 保持稳定
            self.assertEqual(active[0]["title"], "东京羽田航班(改签)")
            self.assertEqual(active[0]["event_date"], "2026-10-26")

            # 4. 到期日程检查（包含逾期 1 天保留，逾期 >1 天过滤）
            # 当前时间 2026-10-25：
            # 2026-10-26 -> 还剩 1 天
            due = inbox_mem.get_due_schedules("2026-10-25")
            self.assertEqual(len(due), 1)
            self.assertEqual(due[0]["due_status"], "还剩 1 天")

            # 当前时间 2026-10-27：
            # 2026-10-26 -> 刚好已逾期 1 天 (delta_days == -1) -> 必须显示
            due_yesterday = inbox_mem.get_due_schedules("2026-10-27")
            self.assertEqual(len(due_yesterday), 1)
            self.assertEqual(due_yesterday[0]["due_status"], "已逾期 1 天")

            # 当前时间 2026-10-28：
            # 2026-10-26 -> 已逾期 2 天 (delta_days == -2) -> 逾期 1 天以上，不再显示！
            due_over_1d = inbox_mem.get_due_schedules("2026-10-28")
            self.assertEqual(len(due_over_1d), 0)

            # 5. 保存并重新加载，验证加解密与反序列化
            inbox_mem.save()
            inbox_reloaded = InboxMemory(filepath=inbox_file, key=self.key)
            self.assertTrue(inbox_reloaded.is_processed("msg-1"))
            self.assertTrue(inbox_reloaded.is_confirmed_spam("msg-2"))
            self.assertEqual(len(inbox_reloaded.get_active_schedules()), 1)

            # 6. 测试通过唯一 schedule_id 移除日程
            deleted = inbox_reloaded.remove_schedule(schedule_id=sched_id)
            self.assertTrue(deleted)
            self.assertEqual(len(inbox_reloaded.get_active_schedules()), 0)

    def test_history_memory_independent_storage(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            history_file = tmp_path / "history.enc"

            hist_mem = HistoryMemory(filepath=history_file, key=self.key)
            self.assertIsInstance(hist_mem.data, HistoryStateData)
            self.assertFalse(hist_mem.is_processed("old-1"))

            hist_mem.mark_processed("old-1")
            hist_mem.record_pruned(10)
            hist_mem.save()

            hist_reloaded = HistoryMemory(filepath=history_file, key=self.key)
            self.assertTrue(hist_reloaded.is_processed("old-1"))
            self.assertEqual(hist_reloaded.data.total_pruned_90d, 10)


if __name__ == "__main__":
    unittest.main()
