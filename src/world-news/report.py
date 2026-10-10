"""
全球宏观、财经与计算开源观察内参 (Global Intelligence, Markets & Technology Briefing)
数据源多源扩充 + AI 多维度评估 + 市场与资产定价传导分析：
1. 宏观与财经源：
   - BBC World News (全球地缘与主权安全)
   - CNBC Markets (全球资本市场、通胀、大宗与宏观政策)
   - Wall Street Journal World (华尔街日报全球权威政经)
2. 科技与开源工程源：
   - Hacker News Top Stories (全球开发者前沿与系统讨论)
   - GitHub Trending (近期爆发性增长的高星前沿开源基础设施与项目)
3. 核心机制：
   - 汇聚 50+ 条候选大池
   - AI 多维度打分：
     * 宏观类：战略地缘(Strategic) / 市场敏感度(Market) / 长期结构外溢(Structural) / 综合评级(Overall)
     * 科技类：架构突破(Novelty) / 商业生态重塑(Ecosystem) / 工程落地实用(Utility) / 综合评级(Overall)
     * 综合得分 < 7.0 分一票否决淘汰
   - 深度剖析资本市场、大宗商品、外汇与科技产业竞争格局的直接/间接传导影响 (Market & Asset Transmission)
"""

import os
import sys
import re
import json
import time
from datetime import datetime, timezone, timedelta
import requests
import feedparser
from dotenv import load_dotenv
from jinja2 import Template

load_dotenv()

# 引入项目根目录以导入 utils
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils.mailer import send_email_html

BJT = timezone(timedelta(hours=8))
now_bjt = datetime.now(BJT)
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "template.html")
SRC_DIR = os.path.dirname(os.path.dirname(__file__))
REPO_ROOT = os.path.dirname(SRC_DIR)
TEMPLATE_PORTAL_FILE = os.path.join(REPO_ROOT, "template_portal.html")
DOCS_ROOT = os.path.join(REPO_ROOT, "docs")
DOCS_DIR = os.path.join(DOCS_ROOT, "world-news")
PAGES_BASE_URL = os.getenv("PAGES_BASE_URL", "https://crimson-and-clover.github.io/daily-actions")


def clean_html(raw_html: str) -> str:
    """去除 HTML 标签"""
    cleanr = re.compile(r'<.*?>')
    return re.sub(cleanr, '', raw_html).strip()


def fetch_macro_finance_feeds() -> list:
    """
    抓取宏观地缘与财经资本市场候选池：
    涵盖 BBC World、CNBC Markets、WSJ World
    """
    sources = [
        {"name": "CNBC Markets", "url": "https://www.cnbc.com/id/10000664/device/rss/rss.html", "limit": 12},
        {"name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "limit": 12},
        {"name": "WSJ World", "url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml", "limit": 10},
    ]
    items = []
    seen_titles = set()
    idx = 0

    for src in sources:
        try:
            feed = feedparser.parse(src["url"])
            count = 0
            for entry in feed.entries:
                title = clean_html(entry.title)
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)

                summary = clean_html(getattr(entry, "summary", ""))
                pub = getattr(entry, "published", "").split(" +")[0]
                items.append({
                    "idx": idx,
                    "source": src["name"],
                    "title": title,
                    "link": entry.link,
                    "summary": summary,
                    "published": pub
                })
                idx += 1
                count += 1
                if count >= src["limit"]:
                    break
        except Exception as e:
            print(f"抓取 {src['name']} 异常: {e}", file=sys.stderr)

    return items


def fetch_tech_opensource_feeds() -> list:
    """
    抓取科技与开源前沿候选池：
    涵盖 Hacker News Top 讨论 + GitHub 新晋高星爆发项目
    """
    items = []
    idx = 0

    # 1. Hacker News Top Stories (前 15 条)
    try:
        top_ids_url = "https://hacker-news.firebaseio.com/v0/topstories.json"
        resp = requests.get(top_ids_url, timeout=10)
        resp.raise_for_status()
        story_ids = resp.json()[:15]

        for s_id in story_ids:
            try:
                item_url = f"https://hacker-news.firebaseio.com/v0/item/{s_id}.json"
                item_resp = requests.get(item_url, timeout=5)
                if item_resp.status_code == 200:
                    d = item_resp.json()
                    title = clean_html(d.get("title", ""))
                    url = d.get("url", f"https://news.ycombinator.com/item?id={s_id}")
                    score = d.get("score", 0)
                    comments = d.get("descendants", 0)
                    items.append({
                        "idx": idx,
                        "type": "hn",
                        "source": "Hacker News",
                        "title": title,
                        "url": url,
                        "hn_url": f"https://news.ycombinator.com/item?id={s_id}",
                        "score": score,
                        "comments": comments,
                        "description": f"社区点赞: {score} | 评论数: {comments}"
                    })
                    idx += 1
            except Exception:
                continue
    except Exception as e:
        print(f"抓取 Hacker News 异常: {e}", file=sys.stderr)

    # 2. GitHub 近 35 天新建且快速爆发的高星新项目 (取前 8 个)
    try:
        since_date = (datetime.now(timezone.utc) - timedelta(days=35)).strftime("%Y-%m-%d")
        gh_url = f"https://api.github.com/search/repositories?q=created:>{since_date}+stars:>150&sort=stars&order=desc&per_page=8"
        headers = {
            "User-Agent": "daily-actions-agent",
            "Accept": "application/vnd.github.v3+json"
        }
        gh_resp = requests.get(gh_url, headers=headers, timeout=10)
        if gh_resp.status_code == 200:
            repos = gh_resp.json().get("items", [])
            for r in repos:
                full_name = r.get("full_name", "")
                desc = clean_html(r.get("description", "") or "暂无官方描述")
                stars = r.get("stargazers_count", 0)
                lang = r.get("language", "Unknown")
                html_url = r.get("html_url", "")

                items.append({
                    "idx": idx,
                    "type": "github",
                    "source": "GitHub Trending",
                    "title": f"[开源新星] {full_name} (语言: {lang} | ★{stars})",
                    "url": html_url,
                    "hn_url": html_url,
                    "score": stars,
                    "comments": r.get("forks_count", 0),
                    "description": f"核心描述: {desc} (语言: {lang}, Stars: {stars})"
                })
                idx += 1
    except Exception as e:
        print(f"抓取 GitHub Trending 异常: {e}", file=sys.stderr)

    return items


def analyze_with_deepseek(macro_items: list, tech_items: list, api_key: str) -> dict:
    """
    调用 DeepSeek 展开多源多维度打分、降噪与【市场资产传导机制】深度研判
    """
    if not api_key:
        print("未检测到 DEEPSEEK_API_KEY，进入基础排版模式。")
        return None

    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    macro_prompt_list = [
        f"[{item['idx']}] 来源: {item['source']} | 标题: {item['title']} | 摘要: {item['summary'][:150]}"
        for item in macro_items
    ]
    tech_prompt_list = [
        f"[{item['idx']}] 来源: {item['source']} | 标题: {item['title']} | 详情: {item['description']}"
        for item in tech_items
    ]

    prompt = f"""
你是一位国际宏观对冲基金首席策略师与资深计算系统架构师。你的核心职责是【信息降噪】与【多维度量化评估 + 市场资产定价与产业传导研判】。
请对以下从多个全球权威渠道抓取的素材进行多维度打分、淘汰低质噪音，并结构化深度研判。

【宏观与财经候选素材 (共 {len(macro_items)} 条，涵盖 CNBC、BBC、WSJ)】:
{chr(10).join(macro_prompt_list)}

【技术与开源候选素材 (共 {len(tech_items)} 条，涵盖 Hacker News、GitHub Trending)】:
{chr(10).join(tech_prompt_list)}

【多维度量化评估评分体系 (各项评分均为 1.0 ~ 10.0，保留一位小数)】：
1. 宏观与财经板块评估维度：
   - strategic: 地缘战略与国家政策重要度（对大国博弈、能源供应、战争与和平、主权制裁的直接影响）
   - market_sensitivity: 资本市场敏感度（对美股板块、大宗原油/黄金、美债收益率、汇率的直接价格驱动力）
   - structural: 长期结构性外溢影响（对全球产业链重塑、跨国法治规则与中长期宏观通胀的深远传导）
   - overall: 综合重要度指数（加权综合判定，必须 >= 7.0 方可准入，< 7.0 绝对淘汰）
2. 计算技术与开源工程板块评估维度：
   - technical_novelty: 底层架构与技术创新度（攻克系统内核、运行时、算法理论或硬件交互等硬核瓶颈）
   - ecosystem_shift: 商业基础设施与生态重塑度（对公有云大厂 AWS/Azure/Cloudflare 护城河、商业开发工具链与开发范式的颠覆能力）
   - production_utility: 工程落地与生产可用度（在生产环境中降本增效、提升并发、降低延迟或修复重大安全风险的真实实用价值）
   - overall: 综合突破度指数（加权综合判定，必须 >= 7.0 方可准入，< 7.0 绝对淘汰）

【硬性淘汰与准入原则】：
1. 绝对淘汰标准（overall < 7.0 分，一律丢弃，绝不可输出）：
   - 娱乐八卦、明星演唱会/私生活、单一刑事个案、地方治安琐事、常规自然天气预报、纯口水战、水文灌水、营销炒作贴。
2. 宁缺毋滥：
   - 宏观财经精选 3~5 条（仅保留 overall >= 7.0 的事件）。
   - 计算开源精选 3~5 条（仅保留 overall >= 7.0 的项目）。

请输出严格合法的 JSON 对象（严禁任何额外字符，严禁任何表情符号），JSON 格式如下：
{{
  "executive_summary": "宏观态势与市场综述（80~120字，冷静客观提炼今日地缘博弈、全球资本市场风险偏好与底层技术突破的核心交汇点）",
  "key_signals": ["核心信号1", "核心信号2", "核心信号3", "核心信号4"],
  "world_events": [
    {{
      "idx": 0,
      "scores": {{
        "strategic": 9.0,
        "market_sensitivity": 8.5,
        "structural": 8.8,
        "overall": 8.8
      }},
      "score_rationale": "评级依据（15~25字，说明为什么具备高战略/市场影响）",
      "tag": "领域分类（如：大宗能源 / 货币政策 / 资本市场 / 地缘安全）",
      "title_zh": "规范客观的中文事件标题",
      "facts": "事实脉络与核心数据（主体、决策数据、具体条款、监管进展）",
      "stakeholders": "博弈方态度（各核心利益相关方的诉求与分歧）",
      "strategic_impact": "产业链与格局（对供应链、地缘格局或宏观经济的链式反应）",
      "market_impact": {{
        "affected_assets": "受影响主要资产（如：原油期货 WTI / 10Y美债收益率 / 美元指数 DXY）",
        "transmission_logic": "市场定价传导机制（明确说明对资产价格是利好、承压还是加剧波动，并解释资金流动与估值影响机理）"
      }}
    }}
  ],
  "tech_trends": [
    {{
      "idx": 0,
      "scores": {{
        "technical_novelty": 9.2,
        "ecosystem_shift": 8.7,
        "production_utility": 8.3,
        "overall": 8.7
      }},
      "score_rationale": "评级依据（15~25字，说明为什么具备重大工程或生态壁垒重塑价值）",
      "tag": "技术分类（如：云原生运行时 / 开源基础设施 / 系统安全 / AI推理系统）",
      "title_zh": "规范严谨的技术/项目标题",
      "tech_definition": "技术定位与核心机理（采用的底层语言与核心架构范式）",
      "problem_solved": "工程瓶颈突破（相比传统方案攻克了什么具体性能/安全/生态痛点）",
      "industry_implication": "生态与工程反响（社区关注焦点与技术壁垒演变）",
      "market_impact": {{
        "affected_assets": "受影响商业标的/赛道（如：公有云厂商 AWS/Azure/Cloudflare、商业开发工具链）",
        "transmission_logic": "产业资本与竞争格局传导（说明该开源项目或技术突破如何影响商业巨头的护城河或行业定价权）"
      }}
    }}
  ]
}}
"""

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are a senior macro hedge fund strategist and systems architect. You strictly output multi-dimensional ratings and professional market-transmission analyses in valid JSON without emojis."},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.15,
        "max_tokens": 4096
    }

    try:
        t0 = time.time()
        print(f"正在调用 DeepSeek 进行跨源多维度打分、降噪与市场影响评估 (候选池: {len(macro_items)} + {len(tech_items)} 条)...")
        resp = requests.post(url, headers=headers, json=payload, timeout=85)
        cost = time.time() - t0

        if resp.status_code == 200:
            res_json = resp.json()
            raw_content = res_json["choices"][0]["message"].get("content", "").strip()
            start = raw_content.find("{")
            end = raw_content.rfind("}")
            if start != -1 and end != -1:
                data = json.loads(raw_content[start:end+1])
                print(f"DeepSeek 多维研读成功！(耗时 {cost:.1f} 秒)")
                return data
        else:
            print(f"DeepSeek API 失败 (HTTP {resp.status_code}): {resp.text[:200]}", file=sys.stderr)
    except Exception as e:
        print(f"DeepSeek 分析异常: {e}", file=sys.stderr)

    return None


def build_html_report(macro_items: list, tech_items: list, ai_analysis: dict = None, pages_url: str = None) -> str:
    """基于独立 template.html 渲染报告（按多维度综合分降序排列）"""
    date_str = now_bjt.strftime("%Y年%m月%d日 (北京时间)")
    macro_by_idx = {item["idx"]: item for item in macro_items}
    tech_by_idx = {item["idx"]: item for item in tech_items}

    # 组装国际与财经事件
    events_data = []
    if ai_analysis and ai_analysis.get("world_events"):
        for ev in ai_analysis["world_events"]:
            scores = ev.get("scores", {})
            overall = float(scores.get("overall", ev.get("score", 7.0)))
            if overall < 7.0:
                continue
            orig = macro_by_idx.get(ev.get("idx"), {})
            events_data.append({
                "scores": {
                    "overall": f"{overall:.1f}",
                    "strategic": f"{float(scores.get('strategic', overall)):.1f}",
                    "market_sensitivity": f"{float(scores.get('market_sensitivity', overall)):.1f}",
                    "structural": f"{float(scores.get('structural', overall)):.1f}"
                },
                "score_rationale": ev.get("score_rationale", ""),
                "tag": ev.get("tag", "宏观财经"),
                "source": orig.get("source", "综合通讯"),
                "title": ev.get("title_zh", orig.get("title", "")),
                "link": orig.get("link", "#"),
                "facts": ev.get("facts", orig.get("summary", "")),
                "stakeholders": ev.get("stakeholders", ""),
                "strategic_impact": ev.get("strategic_impact", ""),
                "market_impact": ev.get("market_impact", {}),
                "original_title": orig.get("title", "")[:50] + "...",
                "published": orig.get("published", "")
            })
        events_data.sort(key=lambda x: float(x["scores"]["overall"]), reverse=True)
    else:
        for item in macro_items[:5]:
            events_data.append({
                "scores": {"overall": "7.0", "strategic": "7.0", "market_sensitivity": "7.0", "structural": "7.0"},
                "score_rationale": "常规基础收录",
                "tag": "宏观事件",
                "source": item.get("source", "公开源"),
                "title": item["title"],
                "link": item["link"],
                "facts": item["summary"],
                "stakeholders": "",
                "strategic_impact": "",
                "market_impact": None,
                "original_title": item["title"],
                "published": item["published"]
            })

    # 组装科技与开源前沿
    trends_data = []
    if ai_analysis and ai_analysis.get("tech_trends"):
        for tr in ai_analysis["tech_trends"]:
            scores = tr.get("scores", {})
            overall = float(scores.get("overall", tr.get("score", 7.0)))
            if overall < 7.0:
                continue
            orig = tech_by_idx.get(tr.get("idx"), {})
            trends_data.append({
                "scores": {
                    "overall": f"{overall:.1f}",
                    "technical_novelty": f"{float(scores.get('technical_novelty', overall)):.1f}",
                    "ecosystem_shift": f"{float(scores.get('ecosystem_shift', overall)):.1f}",
                    "production_utility": f"{float(scores.get('production_utility', overall)):.1f}"
                },
                "score_rationale": tr.get("score_rationale", ""),
                "tag": tr.get("tag", "计算工程"),
                "source": orig.get("source", "开源社区"),
                "title": tr.get("title_zh", orig.get("title", "")),
                "link": orig.get("url", "#"),
                "tech_definition": tr.get("tech_definition", ""),
                "problem_solved": tr.get("problem_solved", ""),
                "industry_implication": tr.get("industry_implication", ""),
                "market_impact": tr.get("market_impact", {}),
                "hn_link": orig.get("hn_url", "#"),
                "original_title": orig.get("title", "")[:45] + "...",
                "hn_score": orig.get("score", 0),
                "comments": orig.get("comments", 0)
            })
        trends_data.sort(key=lambda x: float(x["scores"]["overall"]), reverse=True)
    else:
        for s in tech_items[:5]:
            trends_data.append({
                "scores": {"overall": "7.0", "technical_novelty": "7.0", "ecosystem_shift": "7.0", "production_utility": "7.0"},
                "score_rationale": "常规基础收录",
                "tag": "社区前沿",
                "source": s.get("source", "开源"),
                "title": s["title"],
                "link": s["url"],
                "tech_definition": s["title"],
                "problem_solved": "",
                "industry_implication": "",
                "market_impact": None,
                "hn_link": s["hn_url"],
                "original_title": s["title"][:45] + "...",
                "hn_score": s["score"],
                "comments": s["comments"]
            })

    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = Template(f.read())

    key_signals = ai_analysis.get("key_signals", []) if ai_analysis else ["宏观利率", "大宗能源", "云计算基建", "开源重塑"]

    return template.render(
        date_str=date_str,
        executive_summary=ai_analysis.get("executive_summary") if ai_analysis else None,
        key_signals=key_signals,
        world_events=events_data,
        tech_trends=trends_data,
        pages_url=pages_url
    )


def main():
    print(f"[{now_bjt.strftime('%Y-%m-%d %H:%M:%S')}] 开始生成多源宏观财经与计算开源内参 (多维评分版)...")
    
    macro_items = fetch_macro_finance_feeds()
    print(f"已获取 {len(macro_items)} 条宏观与财经候选素材 (CNBC / BBC / WSJ)")

    tech_items = fetch_tech_opensource_feeds()
    print(f"已获取 {len(tech_items)} 条科技与开源前沿素材 (Hacker News / GitHub Trending)")

    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    ai_analysis = analyze_with_deepseek(macro_items, tech_items, api_key)

    date_str = now_bjt.strftime("%Y-%m-%d")

    # 1. 生成并保存 GitHub Pages 静态站点文档 (docs/world-news/index.html & docs/world-news/archives/{date}.html)
    os.makedirs(DOCS_DIR, exist_ok=True)
    web_html = build_html_report(macro_items, tech_items, ai_analysis, pages_url=None)
    index_path = os.path.join(DOCS_DIR, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(web_html)
    print(f"[网页生成] GitHub Pages 主页已保存: {index_path}")

    # 同时按日期归档
    archive_dir = os.path.join(DOCS_DIR, "archives")
    os.makedirs(archive_dir, exist_ok=True)
    date_path = os.path.join(archive_dir, f"{date_str}.html")
    with open(date_path, "w", encoding="utf-8") as f:
        f.write(web_html)
    print(f"[网页生成] 历史归档已保存: {date_path}")

    # 2. 生成或更新 GitHub Pages 根目录导航页 (docs/index.html)
    root_index_path = os.path.join(DOCS_ROOT, "index.html")
    if os.path.exists(TEMPLATE_PORTAL_FILE):
        with open(TEMPLATE_PORTAL_FILE, "r", encoding="utf-8") as f:
            portal_html = f.read()
        os.makedirs(DOCS_ROOT, exist_ok=True)
        with open(root_index_path, "w", encoding="utf-8") as f:
            f.write(portal_html)
        print(f"[门户生成] 根目录多CI导航主页已更新: {root_index_path}")

    # 3. 生成邮件版本 HTML (包含指向 GitHub Pages 的链接)
    pages_today_url = f"{PAGES_BASE_URL.rstrip('/')}/world-news/index.html"
    email_html = build_html_report(macro_items, tech_items, ai_analysis, pages_url=pages_today_url)

    # 4. 发送邮件并写入本地预览
    subject = f"📊 全球宏观、市场与计算开源内参 [多维评级] ({now_bjt.strftime('%m月%d日')})"
    preview_path = os.path.join(os.path.dirname(__file__), "preview_report.html")
    
    send_email_html(subject, email_html, preview_path)
    print("内参流程执行完成！")


if __name__ == "__main__":
    main()
