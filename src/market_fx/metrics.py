"""
Market FX 统计与指标计算模块：极值区间、真经验百分位数与展示格式化
"""

import pandas as pd


def calculate_metrics(series: pd.Series, scale: float = 1.0, window: int = 30) -> dict | None:
    """计算最新行情、日涨跌及 30 交易日历史统计指标"""
    if series is None or len(series) < 2:
        return None

    scaled_series = series * scale
    current = scaled_series.iloc[-1]
    prev = scaled_series.iloc[-2]
    change = current - prev
    pct_change = (change / prev) * 100 if prev != 0 else 0.0

    tail_win = scaled_series.tail(window)
    low_win = tail_win.min()
    high_win = tail_win.max()
    avg_win = tail_win.mean()

    # 30 日极差相对位置 (Min-Max Position, 0%~100%)
    if high_win > low_win:
        range_pct = max(0.0, min(100.0, (current - low_win) / (high_win - low_win) * 100))
    else:
        range_pct = 50.0

    # 30 日真实经验分位数 (Empirical Quantile)
    percentile = (tail_win <= current).mean() * 100

    return {
        "current": current,
        "prev": prev,
        "change": change,
        "pct_change": pct_change,
        "low_30": low_win,
        "high_30": high_win,
        "avg_30": avg_win,
        "range_pct": range_pct,
        "percentile": percentile,
        "history": scaled_series,
    }


def format_row_display(item_config: dict, metrics: dict | None) -> dict:
    """格式化用于模板渲染的行数据字典"""
    name = item_config["name"]
    symbol = item_config["symbol"]
    decimals = item_config.get("decimals", 2)

    if not metrics:
        return {
            "name": name,
            "symbol": symbol,
            "formatted_price": "-",
            "formatted_change": "-",
            "pct_change": 0.0,
            "formatted_low": "-",
            "formatted_high": "-",
            "range_pct": 50.0,
            "percentile": 50.0,
        }

    curr = metrics["current"]
    chg = metrics["change"]
    pct = metrics["pct_change"]
    low = metrics["low_30"]
    high = metrics["high_30"]
    range_pct = metrics["range_pct"]
    percentile = metrics["percentile"]

    if decimals == 4:
        price_str = f"{curr:.4f}"
        chg_str = f"{chg:+.4f}"
        low_str = f"{low:.4f}"
        high_str = f"{high:.4f}"
    else:
        price_str = f"{curr:,.2f}"
        chg_str = f"{chg:+,.2f}"
        low_str = f"{low:,.2f}"
        high_str = f"{high:,.2f}"

    return {
        "name": name,
        "symbol": symbol,
        "current": curr,
        "formatted_price": price_str,
        "change": chg,
        "formatted_change": chg_str,
        "pct_change": pct,
        "low_30": low,
        "high_30": high,
        "formatted_low": low_str,
        "formatted_high": high_str,
        "range_pct": range_pct,
        "percentile": percentile,
    }


def evaluate_aud(aud_metrics: dict | None) -> dict | None:
    """评估澳元近 30 个交易日定量位置与换汇评级"""
    if not aud_metrics:
        return None
    return {
        "current_str": f"{aud_metrics['current']:.4f}",
        "low_str": f"{aud_metrics['low_30']:.4f}",
        "high_str": f"{aud_metrics['high_30']:.4f}",
        "mean_str": f"{aud_metrics['avg_30']:.4f}",
        "percentile": aud_metrics["percentile"],
        "range_pct": aud_metrics["range_pct"],
    }


def evaluate_vnd(vnd_metrics: dict | None) -> dict | None:
    """计算越南盾多面额快速换算参考"""
    if not vnd_metrics or vnd_metrics["current"] <= 0:
        return None
    curr_rate = vnd_metrics["current"]
    return {
        "rate": curr_rate,
        "vnd100k_to_cny": 100000.0 / curr_rate,
    }
