import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from cryptography.fernet import Fernet

from inbox_agent.engine import build_batch_user_prompt, build_system_prompt
from inbox_agent.imap_client import mutf7_decode, mutf7_encode, parse_folder_name_from_list_line
from inbox_agent.memory import InboxMemory
from inbox_agent.tools import (
    AGENT_TOOLS,
    BatchTracker,
    ToolContext,
    execute_tool,
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

    def test_preferences_lifecycle(self):
        mem = InboxMemory(filepath=self.temp_file)
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

    def test_encryption_persistence(self):
        mem = InboxMemory(filepath=self.temp_file)
        mem.mark_processed("test-msg-123", is_spam=False)
        mem.add_user_preference("发件人含 AWS", "归档至财务", "发票需求")
        mem.save()

        self.assertTrue(self.temp_file.exists())

        # 读取新实例以验证解密载入
        mem2 = InboxMemory(filepath=self.temp_file)
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
        self.client_mock.archive_emails.return_value = 2
        self.client_mock.move_to_spam.return_value = 1
        self.client_mock.create_draft.return_value = {"status": "success", "message": "Draft created"}
        self.client_mock.imap = MagicMock()

        self.test_key = Fernet.generate_key().decode()
        self.temp_file = Path("tests/temp_test_tools_history.enc")
        os.environ["INBOX_STATE_KEY"] = self.test_key
        self.memory = InboxMemory(filepath=self.temp_file)

        self.tracker = BatchTracker()
        self.context = ToolContext(client=self.client_mock, memory=self.memory, tracker=self.tracker)

    def tearDown(self):
        if self.temp_file.exists():
            self.temp_file.unlink()

    def test_tools_schema_definition(self):
        self.assertGreater(len(AGENT_TOOLS), 5)
        names = [t["function"]["name"] for t in AGENT_TOOLS]
        self.assertIn("move_emails", names)
        self.assertIn("read_email_content", names)
        self.assertIn("create_calendar_event", names)
        self.assertIn("create_draft", names)
        self.assertIn("save_user_preference", names)

    def test_resolve_folder_name(self):
        self.assertEqual(resolve_folder_name(self.client_mock, "商业推广"), "&V4NXPpCu-")
        self.assertEqual(resolve_folder_name(self.client_mock, "系统通知"), "&V4NXPpDF-")
        self.assertEqual(resolve_folder_name(self.client_mock, "spam"), "[Gmail]/Spam")
        self.assertEqual(resolve_folder_name(self.client_mock, "INBOX"), "INBOX")

    def test_move_emails_tool(self):
        self.tracker.register_batch_emails([{"uid": "101", "subject": "促销A"}, {"uid": "102", "subject": "促销B"}])
        res = execute_tool(
            "move_emails",
            {"email_uids": ["101", "102"], "target_folder": "商业推广", "category": "marketing", "tldr": "促销折扣"},
            self.context,
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["moved_count"], 2)
        self.assertEqual(self.tracker.marketings_moved_count, 2)
        self.assertEqual(self.tracker.triage_status.get("101"), "marketing")

    def test_create_calendar_event_tool(self):
        self.tracker.register_batch_emails([{"uid": "201", "message_id": "msg_conf_1", "subject": "下周一季度规划会议"}])
        res = execute_tool(
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
        self.assertEqual(res["status"], "success")
        self.assertEqual(self.tracker.triage_status.get("201"), "schedule")
        self.assertEqual(len(self.tracker.schedules), 1)
        self.assertEqual(len(self.memory.data.get("active_schedules", [])), 1)

    def test_create_draft_tool(self):
        res = execute_tool(
            "create_draft",
            {"to": ["partner@example.com"], "subject": "Re: 业务合作", "body": "您好，我们已审阅方案..."},
            self.context,
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(len(self.tracker.created_drafts), 1)

    def test_save_user_preference_tool(self):
        res = execute_tool(
            "save_user_preference",
            {"condition": "发件人含 @notification.service.com", "action_rule": "自动归档至系统通知", "reason": "免打扰"},
            self.context,
        )
        self.assertEqual(res["status"], "success")
        prefs = self.memory.get_user_preferences()
        self.assertEqual(len(prefs), 1)
        self.assertEqual(prefs[0]["action_rule"], "自动归档至系统通知")

    def test_new_categories_tracking(self):
        self.tracker.register_batch_emails([
            {"uid": "301", "subject": "您的验证码是 889201"},
            {"uid": "302", "subject": "招商银行9月账单与证券结单"},
            {"uid": "303", "subject": "北京市税务局纳税人通知公函"},
        ])
        execute_tool(
            "mark_email_flags",
            {"email_uids": ["301"], "category": "verification_code", "is_read": True, "tldr": "登录验证码"},
            self.context,
        )
        execute_tool(
            "mark_email_flags",
            {"email_uids": ["302"], "category": "finance_banking", "is_starred": True, "tldr": "月度对账单"},
            self.context,
        )
        execute_tool(
            "mark_email_flags",
            {"email_uids": ["303"], "category": "government_affairs", "is_starred": True, "tldr": "税务公函"},
            self.context,
        )
        self.assertEqual(len(self.tracker.verification_codes), 1)
        self.assertEqual(len(self.tracker.finance_bankings), 1)
        self.assertEqual(len(self.tracker.government_affairs), 1)
        self.assertEqual(self.tracker.triage_status["301"], "verification_code")
        self.assertEqual(self.tracker.triage_status["302"], "finance_banking")
        self.assertEqual(self.tracker.triage_status["303"], "government_affairs")


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

    def test_prompts_generation(self):
        sys_p = build_system_prompt("my@example.com", "1. 规则A => 动作B")
        self.assertIn("my@example.com", sys_p)
        self.assertIn("规则A => 动作B", sys_p)

        user_p = build_batch_user_prompt([{"uid": "99", "from": "test@test.com", "subject": "测试邮件", "snippet": "这是一段测试摘要"}], 1, 1)
        self.assertIn("[UID: 99]", user_p)
        self.assertIn("这是一段测试摘要", user_p)


if __name__ == "__main__":
    unittest.main()
