"""
Market FX 数据采集模块：网络请求、tenacity 指数退避重试与外汇三角套算
"""

import sys
import time

import pandas as pd
import yfinance as yf
from tenacity import retry, retry_if_result, stop_after_attempt, wait_exponential


def _is_invalid_df(result) -> bool:
    """判断拉取的数据是否无效或行数不足"""
    return result is None or (isinstance(result, pd.DataFrame) and (result.empty or len(result) < 2))


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1.5, min=1.5, max=10), retry=retry_if_result(_is_invalid_df), reraise=False)
def fetch_ticker_with_retry(symbol: str, period: str = "60d") -> pd.DataFrame | None:
    """基于 tenacity 指数退避的单标的数据拉取函数"""
    try:
        t = yf.Ticker(symbol)
        df = t.history(period=period)
        if df is not None and not df.empty and len(df) >= 2:
            return df
        print(f"[{symbol}] 数据不足或暂未生成，tenacity 触发退避重试...", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"[{symbol}] 抓取出现异常: {e}，tenacity 触发退避重试...", file=sys.stderr, flush=True)
    return None


def triangulate_cny_vnd(df_usdvnd: pd.DataFrame | None, df_usdcny: pd.DataFrame | None) -> pd.Series | None:
    """通过 USDVND 与 USDCNY 三角套算生成完整的 CNY/VND 交叉汇率序列"""
    if df_usdvnd is None or df_usdcny is None:
        return None

    try:
        s_vnd = df_usdvnd["Close"]
        s_cny = df_usdcny["Close"]
        df_merged = pd.DataFrame({"vnd": s_vnd, "cny": s_cny}).dropna()
        if len(df_merged) < 2:
            return None
        return df_merged["vnd"] / df_merged["cny"]
    except Exception as e:
        print(f"CNY/VND 三角套算失败: {e}", file=sys.stderr, flush=True)
        return None


def fetch_all_market_data(tickers_config: dict, sleep_interval: float = 0.3) -> dict:
    """全量串行拉取所有配置标的及辅助标的"""
    raw_data = {}
    symbols_to_fetch = []

    for items in tickers_config.values():
        for item in items:
            if item["symbol"] not in symbols_to_fetch:
                symbols_to_fetch.append(item["symbol"])

    if "USDVND=X" not in symbols_to_fetch:
        symbols_to_fetch.append("USDVND=X")

    total = len(symbols_to_fetch)
    for idx, sym in enumerate(symbols_to_fetch, start=1):
        print(f"[{idx}/{total}] 正在拉取 {sym} ...", flush=True)
        raw_data[sym] = fetch_ticker_with_retry(sym)
        if idx < total:
            time.sleep(sleep_interval)

    return raw_data
