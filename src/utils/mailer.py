"""
通用 Gmail 邮件发送模块 (基于 redmail 现代化邮件引擎，集成 tenacity 网络重试)
"""

import smtplib
import sys
from pathlib import Path

from redmail import EmailSender
from tenacity import retry, stop_after_attempt, wait_exponential


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=3, max=15),
    reraise=True,
)
def _dispatch_email_with_retry(
    email: EmailSender,
    subject: str,
    sender: str,
    receivers: list[str],
    html: str,
) -> None:
    """内部带指数退避重试的发信核心逻辑"""
    email.send(
        subject=subject,
        sender=sender,
        receivers=receivers,
        html=html,
    )


def send_email_html(
    subject: str,
    html_content: str,
    gmail_user: str,
    gmail_pass: str,
    receiver: str,
    is_ci: bool = False,
    preview_path: Path = Path("preview.html"),
) -> bool:
    """
    基于 redmail 与 tenacity 重试的 Gmail HTML 邮件发送工具。
    入参明确显式传入邮箱凭据与接收人（已在各 Agent 的 config.py 统一清洗与校验）。
    若未检测到凭证（本地开发），自动保存为本地 HTML 预览文件。
    """
    if not gmail_user or not gmail_pass:
        if is_ci:
            print("❌ [Fatal Error] CI 环境中必须配置 GMAIL_USER 与 GMAIL_APP_PASS，严禁跳过发信！", file=sys.stderr, flush=True)
            sys.exit(1)
        preview_file = preview_path.resolve()
        print(f"⚠️ [提示] 本地未配置 GMAIL_USER 或 GMAIL_APP_PASS，将保存为本地预览文件: {preview_file}", flush=True)
        preview_file.parent.mkdir(parents=True, exist_ok=True)
        preview_file.write_text(html_content, encoding="utf-8")
        print(f"✅ 预览文件已保存至: {preview_file}", flush=True)
        return False

    try:
        print(f"正在通过 redmail 连接 smtp.gmail.com:465 发送邮件至 {receiver} (tenacity 重试保护)...", flush=True)
        email = EmailSender(
            host="smtp.gmail.com",
            port=465,
            username=gmail_user,
            password=gmail_pass,
            cls_smtp=smtplib.SMTP_SSL,
            use_starttls=False,
        )
        _dispatch_email_with_retry(
            email=email,
            subject=subject,
            sender=f"Daily Actions <{gmail_user}>",
            receivers=[receiver],
            html=html_content,
        )
        print(f"✅ 邮件发送成功！主题: {subject}", flush=True)
        return True
    except Exception as e:
        print(f"❌ 邮件发送在 3 次重试后仍失败: {e}", file=sys.stderr, flush=True)
        sys.exit(1)
