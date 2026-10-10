import os
import sys
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

# 自动加载根目录或当前工作目录的 .env 文件
load_dotenv()


def send_email_html(subject: str, html_content: str, preview_path: str = "preview.html") -> bool:
    """
    通用 Gmail 邮件发送工具。
    若未检测到凭证，自动保存为本地 HTML 预览文件，避免报错退出。
    """
    gmail_user = os.getenv("GMAIL_USER")
    gmail_pass = os.getenv("GMAIL_APP_PASS")
    if gmail_pass:
        gmail_pass = gmail_pass.replace(" ", "").strip()
    receiver = os.getenv("NOTIFICATION_EMAIL", gmail_user)

    if not gmail_user or not gmail_pass:
        print(f"⚠️ [提示] 未配置 GMAIL_USER 或 GMAIL_APP_PASS，将保存为本地预览文件: {preview_path}")
        try:
            os.makedirs(os.path.dirname(os.path.abspath(preview_path)), exist_ok=True)
            with open(preview_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            print(f"✅ 预览文件已保存至: {os.path.abspath(preview_path)}")
        except Exception as e:
            print(f"写入预览文件失败: {e}", file=sys.stderr)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Daily Actions <{gmail_user}>"
    msg["To"] = receiver

    part = MIMEText(html_content, "html", "utf-8")
    msg.attach(part)

    try:
        print(f"正在连接 smtp.gmail.com:465 发送邮件至 {receiver} ...")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, [receiver], msg.as_string())
        print(f"✅ 邮件发送成功！主题: {subject}")
        return True
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}", file=sys.stderr)
        sys.exit(1)
