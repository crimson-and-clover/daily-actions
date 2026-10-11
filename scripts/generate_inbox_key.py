#!/usr/bin/env python3
"""
生成 Inbox Agent 状态加密密钥 (Fernet / AES-128-CBC + HMAC-SHA256)
用于在公开 GitHub 仓库中安全加密储存已读邮件与日程待办记忆 (history.enc)
"""

from pathlib import Path

from cryptography.fernet import Fernet

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"


def generate_key():
    key = Fernet.generate_key().decode()
    print("=" * 64)
    print("🔑 [Inbox Agent] 状态对称加密密钥已生成：")
    print(f"\n    {key}\n")
    print("=" * 64)
    print("\n📋 接下来请完成以下两个配置：\n")
    print("1. 【GitHub Actions 线上云端配置 (必需)】")
    print("   进入你的 GitHub 仓库页面：")
    print("   👉 Settings -> Secrets and variables -> Actions -> New repository secret")
    print("   - Name:  INBOX_STATE_KEY")
    print(f"   - Secret: {key}\n")

    print("2. 【本地开发环境配置 (.env)】")
    if ENV_FILE.exists():
        content = ENV_FILE.read_text(encoding="utf-8")
        if "INBOX_STATE_KEY" in content:
            print("   ⚠️  本地 .env 文件中已存在 INBOX_STATE_KEY，未做覆盖。")
        else:
            with ENV_FILE.open("a", encoding="utf-8") as f:
                f.write(f"\n# Inbox Agent 状态加密密钥\nINBOX_STATE_KEY={key}\n")
            print(f"   ✅ 已自动将密钥追加写入本地: {ENV_FILE}")
    else:
        with ENV_FILE.open("w", encoding="utf-8") as f:
            f.write(f"# Inbox Agent 状态加密密钥\nINBOX_STATE_KEY={key}\n")
        print(f"   ✅ 已自动创建并写入本地: {ENV_FILE}")

    print("\n🔒 公开分支上的状态文件 (history.enc) 为完全随机密文，无此密钥绝无法还原。")
    return key


if __name__ == "__main__":
    generate_key()
