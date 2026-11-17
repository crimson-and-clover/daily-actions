"""各任务共用的配置解析工具。"""


def parse_notification_emails(value: str | None, default: str) -> list[str]:
    """解析逗号分隔的收件地址；未提供有效条目时使用默认地址。"""
    addresses = [address.strip() for address in (value or "").split(",") if address.strip()]
    if not addresses:
        addresses = [default.strip()] if default.strip() else []
    return list(dict.fromkeys(addresses))
