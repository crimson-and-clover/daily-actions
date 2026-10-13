import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from cryptography.fernet import Fernet

from inbox_agent.engine import build_batch_user_prompt, build_system_prompt
from inbox_agent.imap import mutf7_decode, mutf7_encode, parse_folder_name_from_list_line
from inbox_agent.memory import InboxMemory
from inbox_agent.tools import (
    AGENT_TOOLS,
    BatchTracker,
    DestinationSpec,
    ToolContext,
    execute_tool,
    get_destination_spec,
    resolve_folder_name,
)


class TestInboxAgentMemory(unittest.TestCase):
    def setUp(self):
        self.test_key = Fernet.generate_key().decode()
        self.temp_file = Path("tests/temp_test_history.enc")
        os.environ["INBOX_STATE_KEY"] = self.test_key

    def tearDown(self):
        if self.temp_file.exists():
            self.temp_file.unlink()

    def test_memory_version_and_upgrade(self):
        mem = InboxMemory(filepath=self.temp_file, key=self.test_key)
        self.assertEqual(mem.data.get("version"), 2)

        # 模拟旧版无 version 数据的升级迁移至版本 2
        old_data = {
            "processed_message_ids": ["msg_1"],
            "total_processed": 1,
        }
        mem.data = old_data
        mem.upgrade_schema()
        self.assertEqual(mem.data["version"], 2)
        self.assertIn("active_schedules", mem.data)
        self.assertIn("user_preferences", mem.data)

    def test_preferences_lifecycle(self):
        mem = InboxMemory(filepath=self.temp_file, key=self.test_key)
        self.assertEqual(len(mem.get_user_preferences()), 0)

        # 添加偏好
        p1 = mem.add_user_preference(
            condition="来自 GitHub 的通知",
            action_rule="归档至系统通知目录并标记已读",
            reason="用户日常习惯",
        )
        self.assertIn("id", p1)
        self.assertEqual(len(mem.get_user_preferences()), 1)

        # 格式化验证
        prompt_str = mem.format_preferences_for_prompt()
        self.assertIn("来自 GitHub 的通知", prompt_str)
        self.assertIn("归档至系统通知目录", prompt_str)

        # 更新相同条件的偏好
        p2 = mem.add_user_preference(
            condition="来自 GitHub 的通知",
            action_rule="归档至系统通知目录并标星",
            reason="更新规则",
        )
        self.assertEqual(p1["id"], p2["id"])
        self.assertEqual(len(mem.get_user_preferences()), 1)
        self.assertEqual(mem.get_user_preferences()[0]["action_rule"], "归档至系统通知目录并标星")

        # 删除偏好
        deleted = mem.remove_user_preference(p1["id"])
        self.assertTrue(deleted)
        self.assertEqual(len(mem.get_user_preferences()), 0)

    def test_calendar_schedules_lifecycle(self):
        mem = InboxMemory(filepath=self.temp_file, key=self.test_key)
        sched1 = {
            "message_id": "msg_meeting_1",
            "subject": "周一团队周会",
            "event_date": "2026-10-20",
            "event_time": "10:00",
            "advance_days": 2,
        }
        sched2 = {
            "message_id": "msg_meeting_2",
            "subject": "产品发版评审",
            "event_date": "2026-10-22",
            "event_time": "15:00",
            "advance_days": 1,
        }
        mem.add_schedule(sched1)
        mem.add_schedule(sched2)
        self.assertEqual(len(mem.get_active_schedules()), 2)

        # 按标题移除日程
        removed = mem.remove_schedule(subject="团队周会")
        self.assertEqual(len(removed), 1)
        self.assertEqual(removed[0]["message_id"], "msg_meeting_1")
        self.assertEqual(len(mem.get_active_schedules()), 1)

        # 按 message_id 移除日程
        removed2 = mem.remove_schedule(message_id="msg_meeting_2")
        self.assertEqual(len(removed2), 1)
        self.assertEqual(len(mem.get_active_schedules()), 0)

    def test_calendar_reschedule_updates_existing(self):
        mem = InboxMemory(filepath=self.temp_file, key=self.test_key)
        mem.add_schedule({
            "message_id": "conf_100",
            "subject": "开会",
            "event_date": "2026-10-25",
        })
        # 改期覆盖更新
        mem.add_schedule({
            "message_id": "conf_100",
            "subject": "开会 (已改期)",
            "event_date": "2026-10-28",
        })
        schedules = mem.get_active_schedules()
        self.assertEqual(len(schedules), 1)
        self.assertEqual(schedules[0]["event_date"], "2026-10-28")
        self.assertEqual(schedules[0]["subject"], "开会 (已改期)")

    def test_encryption_persistence(self):
        mem = InboxMemory(filepath=self.temp_file, key=self.test_key)
        mem.mark_processed("test-msg-123", is_spam=False)
        mem.add_user_preference("发件人含 AWS", "归档至财务", "发票需求")
        mem.save()

        self.assertTrue(self.temp_file.exists())

        # 读取新实例以验证解密载入
        mem2 = InboxMemory(filepath=self.temp_file, key=self.test_key)
        self.assertEqual(mem2.data.get("version"), 2)
        self.assertTrue(mem2.is_processed("test-msg-123"))
        prefs = mem2.get_user_preferences()
        self.assertEqual(len(prefs), 1)
        self.assertEqual(prefs[0]["condition"], "发件人含 AWS")


class TestInboxAgentTools(unittest.TestCase):
    def setUp(self):
        self.client_mock = MagicMock()
        self.client_mock.get_promotions_folder_name.return_value = "&V4NXPpCu-"  # 商业推广
        self.client_mock.get_notifications_folder_name.return_value = "&V4NXPpDF-"  # 系统通知
        self.client_mock.get_spam_folder_name.return_value = "[Gmail]/Spam"
        self.client_mock.get_trash_folder_name.return_value = "[Gmail]/Trash"
        self.client_mock.archive_emails.side_effect = lambda uids, **kwargs: len(uids)
        self.client_mock.move_to_spam.side_effect = lambda uids, **kwargs: len(uids)
        self.client_mock.create_draft.return_value = {"status": "success", "message": "Draft created"}
        self.client_mock.imap = MagicMock()

        self.test_key = Fernet.generate_key().decode()
        self.temp_file = Path("tests/temp_test_tools_history.enc")
        os.environ["INBOX_STATE_KEY"] = self.test_key
        self.memory = InboxMemory(filepath=self.temp_file, key=self.test_key)

        self.tracker = BatchTracker()
        self.context = ToolContext(client=self.client_mock, memory=self.memory, tracker=self.tracker)

    def tearDown(self):
        if self.temp_file.exists():
            self.temp_file.unlink()

    def test_tools_schema_definition(self):
        self.assertGreater(len(AGENT_TOOLS), 5)
        names = [t["function"]["name"] for t in AGENT_TOOLS]
        self.assertIn("move_emails", names)
        self.assertIn("label_emails", names)
        self.assertIn("mark_email_flags", names)
        self.assertIn("read_email_content", names)
        self.assertIn("create_calendar_event", names)
        self.assertIn("list_calendar_events", names)
        self.assertIn("remove_calendar_event", names)
        self.assertIn("create_draft", names)
        self.assertIn("save_user_preference", names)
        self.assertIn("remove_user_preference", names)

    def test_destination_specs(self):
        spec_p = get_destination_spec("promotions", self.client_mock)
        self.assertIsInstance(spec_p, DestinationSpec)
        self.assertEqual(spec_p.destination, "promotions")
        self.assertEqual(spec_p.display_name, "商业推广")
        self.assertEqual(spec_p.folder_id, "&V4NXPpCu-")

        spec_i = get_destination_spec("inbox", self.client_mock)
        self.assertEqual(spec_i.display_name, "收件箱")
        self.assertEqual(spec_i.folder_id, "INBOX")

        with self.assertRaises(ValueError):
            get_destination_spec("non_existent_folder_xyz", self.client_mock)

    def test_invalid_destination_and_labels_raise_error(self):
        # 尝试给不存在的 destination 移动
        with self.assertRaises(ValueError):
            execute_tool(
                "move_emails",
                {"email_uids": ["999"], "destination": "invalid_dest_xyz"},
                self.context,
            )

        # 尝试给不存在的 label 打标签
        with self.assertRaises(ValueError):
            execute_tool(
                "label_emails",
                {"email_uids": ["999"], "labels": ["invalid_label_xyz"]},
                self.context,
            )

    def test_resolve_folder_name(self):
        self.assertEqual(resolve_folder_name(self.client_mock, "商业推广"), "&V4NXPpCu-")
        self.assertEqual(resolve_folder_name(self.client_mock, "系统通知"), "&V4NXPpDF-")
        self.assertEqual(resolve_folder_name(self.client_mock, "spam"), "[Gmail]/Spam")
        self.assertEqual(resolve_folder_name(self.client_mock, "INBOX"), "INBOX")

    def test_orthogonal_three_dimensions_coexistence(self):
        """核心正交测试：一封邮件同时具备留在 INBOX、多个语义标签、加星标、并提取日历待办"""
        self.tracker.register_batch_emails([
            {"uid": "401", "message_id": "msg_bank_401", "subject": "招商银行信用卡账单与还款日通知"},
            {"uid": "402", "message_id": "msg_promo_402", "subject": "国航会员日机票大促优惠券领取"},
        ])

        # 邮件 401：打多重标签（银行账单 + 重要），星标置顶，并提取日程事件
        execute_tool(
            "label_emails",
            {"email_uids": ["401"], "labels": ["finance_banking", "important"], "tldr": "信用卡月结账单"},
            self.context,
        )
        execute_tool(
            "mark_email_flags",
            {"email_uids": ["401"], "is_starred": True},
            self.context,
        )
        execute_tool(
            "create_calendar_event",
            {
                "email_uid": "401",
                "title": "信用卡还款截止日",
                "event_date": "2026-10-25",
                "event_time": "18:00",
                "advance_days": 3,
            },
            self.context,
        )

        dec_401 = self.tracker.triage_decisions["401"]
        self.assertEqual(dec_401["destination"], "inbox")
        self.assertIn("finance_banking", dec_401["labels"])
        self.assertIn("important", dec_401["labels"])
        self.assertTrue(dec_401["triaged"])
        self.assertEqual(len(self.tracker.schedules), 1)
        self.assertEqual(self.tracker.schedules[0]["title"], "信用卡还款截止日")

        # 邮件 402：物理归档至商业推广，同时依然可以提取优惠券截止日到日历待办中！
        execute_tool(
            "move_emails",
            {"email_uids": ["402"], "destination": "promotions", "tldr": "国航促销"},
            self.context,
        )
        execute_tool(
            "create_calendar_event",
            {
                "email_uid": "402",
                "title": "国航优惠券过期提醒",
                "event_date": "2026-10-30",
            },
            self.context,
        )

        dec_402 = self.tracker.triage_decisions["402"]
        self.assertEqual(dec_402["destination"], "promotions")
        self.assertIn("marketing", dec_402["labels"])
        self.assertTrue(dec_402["triaged"])
        self.assertEqual(self.tracker.marketings_moved_count, 1)
        # 日历池独立拥有 2 条日程！物理去向与日程提取完全解耦正交
        self.assertEqual(len(self.tracker.schedules), 2)

    def test_calendar_management_tools(self):
        self.tracker.register_batch_emails([{"uid": "201", "message_id": "msg_conf_1", "subject": "下周一季度规划会议"}])
        # 1. 创建日程
        res_create = execute_tool(
            "create_calendar_event",
            {
                "email_uid": "201",
                "title": "季度规划会议",
                "event_date": "2026-10-20",
                "event_time": "14:00",
                "advance_days": 3,
                "action_items": ["准备Q3汇报文档"],
            },
            self.context,
        )
        self.assertEqual(res_create["status"], "success")
        self.assertEqual(len(self.tracker.schedules), 1)
        self.assertEqual(len(self.memory.get_active_schedules()), 1)

        # 2. 列出日程
        res_list = execute_tool("list_calendar_events", {"keyword": "规划会议"}, self.context)
        self.assertEqual(res_list["status"], "success")
        self.assertEqual(res_list["total"], 1)

        # 3. 移除日程
        res_remove = execute_tool("remove_calendar_event", {"title": "规划会议"}, self.context)
        self.assertEqual(res_remove["status"], "success")
        self.assertEqual(res_remove["removed_count"], 1)
        self.assertEqual(len(self.memory.get_active_schedules()), 0)

    def test_create_draft_tool(self):
        res = execute_tool(
            "create_draft",
            {"to": ["partner@example.com"], "subject": "Re: 业务合作", "body": "您好，我们已审阅方案..."},
            self.context,
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(len(self.tracker.created_drafts), 1)

    def test_save_and_remove_user_preference_tool(self):
        res = execute_tool(
            "save_user_preference",
            {"condition": "发件人含 @notification.service.com", "action_rule": "自动归档至系统通知", "reason": "免打扰"},
            self.context,
        )
        self.assertEqual(res["status"], "success")
        prefs = self.memory.get_user_preferences()
        self.assertEqual(len(prefs), 1)
        self.assertEqual(prefs[0]["action_rule"], "自动归档至系统通知")

        pref_id = prefs[0]["id"]
        res_del = execute_tool("remove_user_preference", {"preference_id": pref_id}, self.context)
        self.assertEqual(res_del["status"], "success")
        self.assertEqual(len(self.memory.get_user_preferences()), 0)

    def test_labels_tracking(self):
        self.tracker.register_batch_emails([
            {"uid": "301", "subject": "您的验证码是 889201"},
            {"uid": "302", "subject": "招商银行9月账单与证券结单"},
            {"uid": "303", "subject": "北京市税务局纳税人通知公函"},
        ])
        execute_tool(
            "label_emails",
            {"email_uids": ["301"], "labels": ["verification_code"], "tldr": "登录验证码"},
            self.context,
        )
        execute_tool(
            "label_emails",
            {"email_uids": ["302"], "labels": ["finance_banking"], "tldr": "月度对账单"},
            self.context,
        )
        execute_tool(
            "label_emails",
            {"email_uids": ["303"], "labels": ["government_affairs"], "tldr": "税务公函"},
            self.context,
        )
        self.assertEqual(len(self.tracker.verification_codes), 1)
        self.assertEqual(len(self.tracker.finance_bankings), 1)
        self.assertEqual(len(self.tracker.government_affairs), 1)


class TestIMAPAndPrompts(unittest.TestCase):
    def test_mutf7_encode_decode(self):
        chinese_name = "商业推广"
        encoded = mutf7_encode(chinese_name)
        decoded = mutf7_decode(encoded)
        self.assertEqual(decoded, chinese_name)

    def test_parse_folder_name_from_list_line(self):
        sample_line = r'(\HasNoChildren \Spam) "/" "[Gmail]/&V4NXPpCu-"'
        flags, name = parse_folder_name_from_list_line(sample_line)
        self.assertIn(r"\Spam", flags)
        self.assertEqual(name, "[Gmail]/&V4NXPpCu-")

        # 测试未加引号的 INBOX
        sample_inbox = r'(\HasNoChildren) "/" INBOX'
        flags_inbox, name_inbox = parse_folder_name_from_list_line(sample_inbox)
        self.assertEqual(name_inbox, "INBOX")

    def test_prompts_generation(self):
        sys_p = build_system_prompt("my@example.com", "1. 规则A => 动作B")
        self.assertIn("my@example.com", sys_p)
        self.assertIn("规则A => 动作B", sys_p)

        user_p = build_batch_user_prompt(
            [{"uid": "99", "from": "test@test.com", "subject": "测试邮件", "snippet": "这是一段测试摘要"}], 1, 1
        )
        self.assertIn("[UID: 99]", user_p)
        self.assertIn("这是一段测试摘要", user_p)


if __name__ == "__main__":
    unittest.main()
