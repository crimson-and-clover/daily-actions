"""
时区与基准时间统一管理模块 (Timezone Utilities)
提供统一的北京时间 (UTC+8) 对象及公历日期、星期格式化工具
"""

from datetime import datetime, timedelta, timezone

BJT = timezone(timedelta(hours=8))

WEEKDAY_NAMES = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def get_now_bjt() -> datetime:
    """获取当前北京时间 datetime 对象"""
    return datetime.now(BJT)


def get_bjt_date_str(fmt: str = "%Y-%m-%d") -> str:
    """获取当前北京时间的公历日期字符串"""
    return get_now_bjt().strftime(fmt)


def get_bjt_weekday_str() -> str:
    """获取当前北京时间的星期字符串 (如 星期一)"""
    return WEEKDAY_NAMES[get_now_bjt().weekday()]
