"""
每日全球金融市场行情与旅行汇率简报
- 美股三大指数 (S&P 500, Nasdaq, Dow Jones)
- 核心科技与 AI 标的 (NVDA, TSLA, GOOGL, AAPL, MSFT)
- 黄金与宏观指标 (Gold, DXY, 10Y Yield)
- 澳洲与越南旅行汇率及智能换汇提醒 (AUD/CNY, CNY/VND, USD/CNY)
"""

import os
import sys
from datetime import datetime, timezone, timedelta
import yfinance as yf
import pandas as pd

# 引入项目根目录以导入 utils
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils.mailer import send_email_html

# 北京时间 (UTC+8)
BJT = timezone(timedelta(hours=8))
now_bjt = datetime.now(BJT)

# 标的定义
TICKERS_CONFIG = {
    "indices": [
        {"symbol": "^GSPC", "name": "标普500 (S&P 500)"},
        {"symbol": "^IXIC", "name": "纳斯达克 (Nasdaq)"},
        {"symbol": "^DJI", "name": "道琼斯 (Dow Jones)"},
    ],
    "tech_ai": [
        {"symbol": "NVDA", "name": "英伟达 (NVIDIA)"},
        {"symbol": "TSLA", "name": "特斯拉 (Tesla)"},
        {"symbol": "GOOGL", "name": "谷歌 (Alphabet)"},
        {"symbol": "AAPL", "name": "苹果 (Apple)"},
        {"symbol": "MSFT", "name": "微软 (Microsoft)"},
    ],
    "commodities_macro": [
        {"symbol": "GC=F", "name": "COMEX 黄金期货 (Gold)"},
        {"symbol": "DX-Y.NYB", "name": "美元指数 (DXY)"},
        {"symbol": "^TNX", "name": "美债10年期收益率 (10Y Yield)"},
    ],
    "fx_travel": [
        {"symbol": "AUDCNY=X", "name": "澳元 / 人民币 (AUD/CNY)"},
        {"symbol": "CNYVND=X", "name": "人民币 / 越南盾 (CNY/VND)"},
        {"symbol": "USDCNY=X", "name": "美元 / 人民币 (USD/CNY)"},
    ]
}


def get_quote_data(symbol: str, history_days: int = 60):
    """获取单个标的历史数据并计算涨跌"""
    try:
        t = yf.Ticker(symbol)
        df = t.history(period=f"{history_days}d")
        if df.empty or len(df) < 2:
            return None
        
        current = df["Close"].iloc[-1]
        prev = df["Close"].iloc[-2]
        change = current - prev
        pct_change = (change / prev) * 100
        
        return {
            "symbol": symbol,
            "current": current,
            "prev": prev,
            "change": change,
            "pct_change": pct_change,
            "history": df["Close"]
        }
    except Exception as e:
        print(f"Error fetching {symbol}: {e}", file=sys.stderr)
        return None


def analyze_aud(aud_series: pd.Series):
    """分析近 30 个交易日澳元汇率走势与换汇建议"""
    if aud_series is None or len(aud_series) < 10:
        return "数据不足，暂无法生成建议"
    
    last_30 = aud_series.tail(30)
    current = last_30.iloc[-1]
    low_30 = last_30.min()
    high_30 = last_30.max()
    avg_30 = last_30.mean()
    
    # 计算当前在近 30 天区间中的百分位
    if high_30 > low_30:
        pctile = (current - low_30) / (high_30 - low_30) * 100
    else:
        pctile = 50.0
        
    if pctile <= 30:
        advice = (
            f"<b style='color: #16a34a;'>🟢 极佳换汇时机</b>：当前汇率处于近30天 <b>{pctile:.0f}%</b> 低位区间 "
            f"(30天最低: <b>{low_30:.4f}</b>，最高: <b>{high_30:.4f}</b>，均值: <b>{avg_30:.4f}</b>)。"
            f"<br>建议分批买入澳元现汇或锁定出行预算！"
        )
    elif pctile >= 70:
        advice = (
            f"<b style='color: #dc2626;'>🔴 偏高观望</b>：当前汇率处于近30天 <b>{pctile:.0f}%</b> 高位区间 "
            f"(30天最高: <b>{high_30:.4f}</b>)。"
            f"<br>汇率偏高，建议暂缓换汇，等待回调。"
        )
    else:
        advice = (
            f"<b style='color: #d97706;'>🟡 中位平稳</b>：当前汇率处于近30天 <b>{pctile:.0f}%</b> 中间区间 "
            f"(30天区间: <b>{low_30:.4f} ~ {high_30:.4f}</b>)。"
            f"<br>根据实际行程需求逢低按需分批兑换。"
        )
    return advice


def format_cell(data, is_fx=False):
    """格式化单行表格数据"""
    if not data:
        return "<td>-</td><td>-</td><td>-</td>"
    
    curr = data["current"]
    chg = data["change"]
    pct = data["pct_change"]
    
    if pct >= 0:
        color = "#16a34a"  # 绿色涨
        badge = f"<span style='color: {color}; font-weight: bold;'>▲ +{pct:.2f}%</span>"
    else:
        color = "#dc2626"  # 红色跌
        badge = f"<span style='color: {color}; font-weight: bold;'>▼ {pct:.2f}%</span>"
        
    if is_fx:
        val_str = f"<b>{curr:,.2f}</b>" if curr > 100 else f"<b>{curr:.4f}</b>"
        chg_str = f"{chg:+,.2f}" if abs(chg) > 10 else f"{chg:+.4f}"
    elif curr > 1000:
        val_str = f"<b>{curr:,.2f}</b>"
        chg_str = f"{chg:+,.2f}"
    else:
        val_str = f"<b>{curr:.2f}</b>"
        chg_str = f"{chg:+.2f}"
        
    return f"<td>{val_str}</td><td style='color: #64748b;'>{chg_str}</td><td>{badge}</td>"


def build_html_report(results):
    """生成排版精美的 HTML 邮件"""
    date_str = now_bjt.strftime("%Y年%m月%d日 %H:%M (北京时间)")
    
    # 澳元建议
    aud_data = results.get("AUDCNY=X")
    aud_advice = analyze_aud(aud_data["history"] if aud_data else None)
    
    # 越南盾换算
    vnd_data = results.get("CNYVND=X")
    vnd_tips = ""
    if vnd_data:
        cny_to_vnd = vnd_data["current"]
        if cny_to_vnd > 0:
            vnd_to_cny_100k = 100000.0 / cny_to_vnd
            vnd_tips = (
                f"<b>🇻🇳 越南盾快速换算参考</b>：<br>"
                f"• 1 人民币 (CNY) ≈ <b>{cny_to_vnd:,.0f}</b> 越南盾 (VND)<br>"
                f"• 100 人民币 (CNY) ≈ <b>{cny_to_vnd*100:,.0f}</b> 越南盾 (VND)<br>"
                f"• 100,000 越南盾 (VND) ≈ <b>{vnd_to_cny_100k:.2f}</b> 人民币 (CNY)"
            )

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 20px; color: #1e293b; }}
            .container {{ max-width: 650px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); border: 1px solid #e2e8f0; }}
            .header {{ background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%); color: #ffffff; padding: 24px; text-align: center; }}
            .header h1 {{ margin: 0; font-size: 22px; font-weight: 700; }}
            .header p {{ margin: 6px 0 0 0; font-size: 13px; opacity: 0.9; }}
            .content {{ padding: 24px; }}
            .section {{ margin-bottom: 24px; }}
            .section-title {{ font-size: 16px; font-weight: 700; color: #0f172a; margin-bottom: 12px; display: flex; align-items: center; border-bottom: 2px solid #e2e8f0; padding-bottom: 6px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 14px; }}
            th {{ text-align: left; padding: 10px 8px; background-color: #f1f5f9; color: #475569; font-weight: 600; font-size: 13px; border-radius: 4px; }}
            td {{ padding: 10px 8px; border-bottom: 1px solid #f1f5f9; }}
            .card {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; margin-top: 10px; font-size: 13px; line-height: 1.6; }}
            .footer {{ text-align: center; padding: 16px; font-size: 12px; color: #94a3b8; border-top: 1px solid #e2e8f0; background: #fafafa; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>📊 每日金融市场行情 & 旅行汇率早报</h1>
                <p>{date_str}</p>
            </div>
            <div class="content">
                <!-- 旅游与外汇看板 -->
                <div class="section">
                    <div class="section-title">✈️ 澳大利亚 & 越南旅游汇率看板</div>
                    <table>
                        <tr><th>货币对</th><th>最新汇率</th><th>涨跌</th><th>幅度</th></tr>
    """
    
    for item in TICKERS_CONFIG["fx_travel"]:
        d = results.get(item["symbol"])
        html += f"<tr><td><b>{item['name']}</b></td>{format_cell(d, is_fx=True)}</tr>"
        
    html += f"""
                    </table>
                    <div class="card" style="border-left: 4px solid #3b82f6;">
                        <div style="font-weight: 600; margin-bottom: 4px;">🦘 澳元换汇智能提醒：</div>
                        {aud_advice}
                    </div>
    """
    
    if vnd_tips:
        html += f"""
                    <div class="card" style="border-left: 4px solid #10b981; margin-top: 8px;">
                        {vnd_tips}
                    </div>
        """
        
    # 黄金与宏观指标
    html += """
                </div>
                <div class="section">
                    <div class="section-title">🏆 黄金与宏观市场</div>
                    <table>
                        <tr><th>指标/资产</th><th>最新价</th><th>涨跌</th><th>幅度</th></tr>
    """
    for item in TICKERS_CONFIG["commodities_macro"]:
        d = results.get(item["symbol"])
        html += f"<tr><td><b>{item['name']}</b></td>{format_cell(d)}</tr>"
        
    # 美股三大指数
    html += """
                    </table>
                </div>
                <div class="section">
                    <div class="section-title">📈 美股三大指数收盘</div>
                    <table>
                        <tr><th>指数</th><th>收盘点位</th><th>点数变动</th><th>涨跌幅</th></tr>
    """
    for item in TICKERS_CONFIG["indices"]:
        d = results.get(item["symbol"])
        html += f"<tr><td><b>{item['name']}</b></td>{format_cell(d)}</tr>"

    # 核心科技与 AI
    html += """
                    </table>
                </div>
                <div class="section">
                    <div class="section-title">💻 科技与 AI 核心资产</div>
                    <table>
                        <tr><th>标的</th><th>最新价 (USD)</th><th>涨跌</th><th>涨跌幅</th></tr>
    """
    for item in TICKERS_CONFIG["tech_ai"]:
        d = results.get(item["symbol"])
        html += f"<tr><td><b>{item['name']}</b></td>{format_cell(d)}</tr>"

    html += """
                    </table>
                </div>
            </div>
            <div class="footer">
                由 GitHub Actions 与 uv 自动化构建与发送 • 数据源自 Yahoo Finance
            </div>
        </div>
    </body>
    </html>
    """
    return html


def main():
    print(f"[{now_bjt.strftime('%Y-%m-%d %H:%M:%S')}] 开始获取全球行情与汇率数据...")
    
    all_symbols = []
    for category in TICKERS_CONFIG.values():
        for item in category:
            all_symbols.append(item["symbol"])
            
    results = {}
    for sym in all_symbols:
        print(f"-> 正在拉取 {sym} ...")
        results[sym] = get_quote_data(sym)
        
    html = build_html_report(results)
    subject = f"📊 金融早报 & 旅游汇率 ({now_bjt.strftime('%m月%d日')})"
    preview_path = os.path.join(os.path.dirname(__file__), "preview_report.html")
    send_email_html(subject, html, preview_path)
    print("全部流程执行完成！")


if __name__ == "__main__":
    main()
