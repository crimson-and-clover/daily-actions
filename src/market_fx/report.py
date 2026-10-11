"""
每日全球金融市场行情与主流外汇简报 - 主入口流程编排器
"""

import logging
import sys

from dotenv import load_dotenv

from market_fx.config import TICKERS_CONFIG, get_now_bjt, validate_config
from market_fx.fetcher import fetch_all_market_data, triangulate_cny_vnd
from market_fx.memory import MarketMemory
from market_fx.metrics import calculate_metrics, evaluate_aud, evaluate_vnd, format_row_display
from market_fx.publisher import publish_reports

# 强制开启实时无缓冲日志输出，防止重定向管道缓存导致日志延迟
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

# 静默 yfinance 无害告警
logging.getLogger("yfinance").setLevel(logging.ERROR)

load_dotenv()


def main():
    validate_config()
    now_dt = get_now_bjt()
    date_str = now_dt.strftime("%Y年%m月%d日 %H:%M (北京时间)")
    iso_date_str = now_dt.strftime("%Y-%m-%d")
    print(f"[{now_dt.strftime('%Y-%m-%d %H:%M:%S')}] 开始采集全球金融市场行情与主流外汇数据...", flush=True)

    # 1. 串行拉取各标的行情与历史序列
    raw_data = fetch_all_market_data(TICKERS_CONFIG)
    valid_count = sum(1 for df in raw_data.values() if df is not None and not df.empty)
    if valid_count == 0:
        print("[Fatal Error] 全量市场标的数据拉取均失败，网络或 yfinance 接口异常！", file=sys.stderr)
        sys.exit(1)

    # 2. 计算主流外汇行与指标
    fx_major_rows = []
    for item in TICKERS_CONFIG["fx_major"]:
        df = raw_data.get(item["symbol"])
        metrics = calculate_metrics(df["Close"] if df is not None else None, scale=item["scale"])
        fx_major_rows.append(format_row_display(item, metrics))

    # 3. 计算出境外汇（含三角套算越南盾）
    fx_travel_rows = []
    for item in TICKERS_CONFIG["fx_travel"]:
        df = raw_data.get(item["symbol"])
        metrics = calculate_metrics(df["Close"] if df is not None else None, scale=item["scale"])
        fx_travel_rows.append(format_row_display(item, metrics))

    cny_vnd_series = triangulate_cny_vnd(raw_data.get("USDVND=X"), raw_data.get("USDCNY=X"))
    cny_vnd_metrics = calculate_metrics(cny_vnd_series, scale=1.0) if cny_vnd_series is not None else None
    vnd_config = {"name": "人民币 / 越南盾 (CNY/VND)", "symbol": "CNYVND (套算)", "decimals": 2}
    fx_travel_rows.append(format_row_display(vnd_config, cny_vnd_metrics))

    # 4. 计算宏观大宗、指数与科技巨头
    macro_rows = []
    for item in TICKERS_CONFIG["commodities_macro"]:
        df = raw_data.get(item["symbol"])
        metrics = calculate_metrics(df["Close"] if df is not None else None, scale=item["scale"])
        macro_rows.append(format_row_display(item, metrics))

    indices_rows = []
    for item in TICKERS_CONFIG["indices"]:
        df = raw_data.get(item["symbol"])
        metrics = calculate_metrics(df["Close"] if df is not None else None, scale=item["scale"])
        indices_rows.append(format_row_display(item, metrics))

    tech_rows = []
    for item in TICKERS_CONFIG["tech_stocks"]:
        df = raw_data.get(item["symbol"])
        metrics = calculate_metrics(df["Close"] if df is not None else None, scale=item["scale"])
        tech_rows.append(format_row_display(item, metrics))

    # 5. 特色外汇定量评估卡片
    aud_df = raw_data.get("AUDCNY=X")
    aud_metrics = calculate_metrics(aud_df["Close"] if aud_df is not None else None, scale=1.0)
    aud_stat = evaluate_aud(aud_metrics)
    vnd_stat = evaluate_vnd(cny_vnd_metrics)

    # 6. 持久化当日快照至 memory (对接 state/market-fx 分支)
    memory = MarketMemory()
    snapshot = {
        "timestamp": now_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "fx_major": {row["symbol"]: row.get("current") for row in fx_major_rows if "current" in row},
        "fx_travel": {row["symbol"]: row.get("current") for row in fx_travel_rows if "current" in row},
        "macro": {row["symbol"]: row.get("current") for row in macro_rows if "current" in row},
        "indices": {row["symbol"]: row.get("current") for row in indices_rows if "current" in row},
        "tech_stocks": {row["symbol"]: row.get("current") for row in tech_rows if "current" in row},
        "aud_quantile": aud_stat["percentile"] if aud_stat else None,
        "vnd_rate": vnd_stat["rate"] if vnd_stat else None,
    }
    memory.record_snapshot(iso_date_str, snapshot)
    memory.save()

    # 7. 组装渲染上下文并统一发布页面、更新门户及发送邮件
    render_context = {
        "date_str": date_str,
        "fx_major": fx_major_rows,
        "fx_travel": fx_travel_rows,
        "macro": macro_rows,
        "indices": indices_rows,
        "tech_stocks": tech_rows,
        "aud_stat": aud_stat,
        "vnd_stat": vnd_stat,
    }
    # 生成高密度干练主题 (去除Emoji，提炼USD/CNY及大盘关键异动)
    usd_row = next((r for r in fx_major_rows if "USD" in r.get("symbol", "")), None)
    spx_row = next((r for r in indices_rows if "^GSPC" in r.get("symbol", "") or "S&P" in r.get("name", "")), None)
    btc_row = next((r for r in macro_rows if "BTC" in r.get("symbol", "")), None)

    summary_parts = []
    if usd_row and usd_row.get("formatted_price") != "-":
        summary_parts.append(f"USD/CNY {usd_row['formatted_price']} ({usd_row['pct_change']:+.2f}%)")
    if spx_row and spx_row.get("formatted_price") != "-":
        summary_parts.append(f"S&P500 {spx_row['pct_change']:+.2f}%")
    if btc_row and btc_row.get("formatted_price") != "-":
        summary_parts.append(f"BTC {btc_row['pct_change']:+.2f}%")

    market_brief = " | ".join(summary_parts) if summary_parts else "全景快照"
    subject = f"[Market FX] {iso_date_str} 全球宏观与外汇简报: {market_brief}"
    publish_reports(render_context, iso_date_str, subject)
    print("流程全部顺利执行完成！", flush=True)


if __name__ == "__main__":
    main()
