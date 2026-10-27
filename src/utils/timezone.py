"""
时区与基准时间统一管理模块 (Timezone Utilities)
基于 pendulum 提供统一的北京时间 (UTC+8) 对象、时区解析与日期强类型处理工具
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any

import pendulum
from dateutil import parser as dateutil_parser
from pendulum import DateTime

# 核心基准时区：北京时间 (UTC+8)
BJT_TIMEZONE_NAME = "Asia/Shanghai"
BJT = timezone(timedelta(hours=8))

WEEKDAY_NAMES = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def get_now_bjt() -> DateTime:
    """获取当前北京时间的 pendulum DateTime 对象 (具备完整时区上下文)"""
    return pendulum.now(BJT_TIMEZONE_NAME)


def parse_bjt_datetime(val: Any, default_tz: str = BJT_TIMEZONE_NAME) -> DateTime:
    """
    智能解析任意输入（ISO-8601 字符串、RFC 2822、标准 datetime、date 等）并转换为带时区的 DateTime 实体。
    如果输入不含时区信息，默认绑定 default_tz (Asia/Shanghai)。
    """
    if isinstance(val, DateTime):
        return val.in_timezone(default_tz)
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return pendulum.datetime(
                val.year, val.month, val.day, val.hour, val.minute, val.second, val.microsecond, tz=default_tz
            )
        return pendulum.instance(val).in_timezone(default_tz)
    if isinstance(val, date):
        return pendulum.datetime(val.year, val.month, val.day, tz=default_tz)

    val_str = str(val).strip()
    if not val_str:
        return get_now_bjt()

    # 1. 优先尝试 pendulum 的高效自适应解析
    try:
        parsed = pendulum.parse(val_str, tz=default_tz)
        if isinstance(parsed, DateTime):
            return parsed.in_timezone(default_tz)
        if isinstance(parsed, date):
            return pendulum.datetime(parsed.year, parsed.month, parsed.day, tz=default_tz)
    except Exception:
        pass

    # 2. 回退到 dateutil 模糊解析以防极端边缘字符串
    dt = dateutil_parser.parse(val_str)
    if dt.tzinfo is None:
        return pendulum.datetime(
            dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond, tz=default_tz
        )
    return pendulum.instance(dt).in_timezone(default_tz)


def get_bjt_date_str(fmt: str = "%Y-%m-%d") -> str:
    """获取当前北京时间的公历日期字符串"""
    return get_now_bjt().strftime(fmt)


def get_bjt_weekday_str() -> str:
    """获取当前北京时间的星期字符串 (如 星期一)"""
    return WEEKDAY_NAMES[get_now_bjt().weekday()]
