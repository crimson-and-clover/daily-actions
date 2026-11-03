"""PR #26 的查询交付顺序与垃圾箱未决状态回归测试。"""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from inbox_agent.agent import main
from inbox_agent.engine import AgentEngine
from inbox_agent.imap.models import Email
from inbox_agent.memory import InboxMemory, ScheduleItem
from inbox_agent.tools import ToolContext


def make_email():
    return Email(
        uid=501, message_id="<test@example.com>", subject="待复核邮件",
        from_addr="sender@example.com", to_addr="me@example.com",
        date="2026-11-03", snippet="摘要", body="正文",
    )


def tool(call_id, name, args):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def response(calls):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=calls))])


class TestInboxReviewRegressions(unittest.TestCase):
    def setUp(self):
        self.memory = MagicMock(spec=InboxMemory)
        self.context = ToolContext(
            connection=MagicMock(), repo=MagicMock(), label_service=MagicMock(),
            flag_service=MagicMock(), draft_service=MagicMock(), memory=self.memory,
        )
        self.engine = AgentEngine(api_key="")
        self.engine.client = MagicMock()

    def test_first_query_cannot_unlock_writes_in_same_turn(self):
        self.memory.get_active_schedules.return_value = [{"schedule_id": "old-event", "title": "旧日程"}]
        self.memory.add_schedule.side_effect = ScheduleItem.model_validate
        self.memory.remove_schedule.return_value = True
        create = {"title": "会议", "event_date": "2099-01-01", "message_id": "<test@example.com>"}
        self.engine.client.chat.completions.create.side_effect = [
            response([
                tool("list", "list_calendar_events", {}),
                tool("early-create", "create_calendar_event", create),
                tool("early-remove", "remove_calendar_event", {"schedule_id": "old-event"}),
            ]),
            response([
                tool("create", "create_calendar_event", create),
                tool("remove", "remove_calendar_event", {"schedule_id": "old-event"}),
            ]),
        ]
        self.engine.run_batch_triage([make_email()], 1, 1, self.context, max_turns=2)
        messages = self.engine.client.chat.completions.create.call_args.kwargs["messages"]
        results = {m["tool_call_id"]: json.loads(m["content"]) for m in messages if m["role"] == "tool"}
        self.assertEqual(results["early-create"]["code"], "calendar_check_required")
        self.assertEqual(results["early-remove"]["code"], "calendar_check_required")
        self.assertEqual(results["create"]["status"], "success")
        self.assertEqual(results["remove"]["status"], "success")
        self.memory.get_active_schedules.assert_called_once()
        self.memory.add_schedule.assert_called_once()
        self.memory.remove_schedule.assert_called_once_with("old-event")

    def test_failed_query_does_not_unlock_next_turn(self):
        self.memory.get_active_schedules.side_effect = RuntimeError("查询失败")
        self.engine.client.chat.completions.create.side_effect = [
            response([tool("list", "list_calendar_events", {})]),
            response([tool("remove", "remove_calendar_event", {"schedule_id": "old-event"})]),
        ]
        self.engine.run_batch_triage([make_email()], 1, 1, self.context, max_turns=2)
        self.memory.remove_schedule.assert_not_called()
        self.assertFalse(self.context.calendar_checked)

    def test_unresolved_spam_keeps_retry_opportunity(self):
        self.memory.is_processed.return_value = False
        self.memory.get_due_schedules.return_value = []
        with (
            patch("inbox_agent.agent.validate_config"),
            patch("inbox_agent.agent.InboxMemory", return_value=self.memory),
            patch("inbox_agent.agent.ImapConnection"),
            patch("inbox_agent.agent.MessageRepo") as repo,
            patch("inbox_agent.agent.AgentEngine") as engine,
            patch("inbox_agent.agent.send_email_html") as send,
        ):
            repo.return_value.fetch_emails.side_effect = [[], [make_email()]]
            engine.return_value.run_batch_triage.return_value = "读取失败，保留未决"
            main()
        self.memory.mark_processed.assert_not_called()
        self.assertFalse(self.memory.is_processed(make_email().message_id))
        send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
