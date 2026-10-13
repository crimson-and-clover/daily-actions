"""
Inbox Agent 交互式多轮对话客户端 (CLI Chat Mode)
支持自然语言交互、多轮对话驱动、即时邮件检索、深度分析、草稿拟定与偏好沉淀
"""

import sys

from inbox_agent.config import (
    DEEPSEEK_API_KEY,
    GMAIL_APP_PASS,
    GMAIL_USER,
    get_now_bjt,
    validate_config,
)
from inbox_agent.engine import AgentEngine
from inbox_agent.imap_client import GmailClient
from inbox_agent.memory import InboxMemory
from inbox_agent.tools import BatchTracker, ToolContext


def start_chat():
    validate_config(require_deepseek=True)
    now_dt = get_now_bjt()
    print("=" * 60)
    print(f"📬 [Inbox Agent] 邮件交互助手已就绪 ({now_dt.strftime('%Y-%m-%d %H:%M:%S')} BJT)")
    print("支持多轮对话、自主工具检索、读信、建日程、拟草稿与偏好记忆")
    print("输入 'exit' 或 'quit' 退出，输入 'clear' 重置当前对话上下文")
    print("=" * 60)

    memory = InboxMemory()
    client = GmailClient(username=GMAIL_USER, password=GMAIL_APP_PASS)

    print("[IMAP] 正在连接 Gmail 邮箱...")
    if not client.connect():
        print("[IMAP Error] 登录失败，请检查 GMAIL_USER 与 GMAIL_APP_PASS", file=sys.stderr)
        sys.exit(1)
    print("[IMAP] 连接成功！\n")

    tracker = BatchTracker()
    context = ToolContext(client=client, memory=memory, tracker=tracker)
    engine = AgentEngine(api_key=DEEPSEEK_API_KEY)

    conversation_history = []

    try:
        while True:
            try:
                user_input = input("\n你 > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n收到退出指令。")
                break

            if not user_input:
                continue

            if user_input.lower() in ["exit", "quit", "q"]:
                break

            if user_input.lower() in ["clear", "reset"]:
                conversation_history = []
                print("[系统] 对话上下文已重置。")
                continue

            print("Agent 思考并决策中...")
            reply = engine.run_interactive_turn(
                conversation_history=conversation_history,
                user_input=user_input,
                context=context,
                user_email=GMAIL_USER,
            )
            print(f"\nAgent >\n{reply}")

    finally:
        memory.save()
        if client.imap:
            client.close()
        print("\n=== 对话结束，状态已安全持久化 ===")


if __name__ == "__main__":
    start_chat()
