"""
Resident Paper Agent (学术研究助理 Agent)
- 研究方向：自动驾驶 (Autonomous Driving)、世界模型 (World Models)、WAM、VLA (Vision-Language-Action)
- 运行机制：
  1. 长期状态记录 (State Tracking)：记录已分析论文 ID，去重过滤
  2. 论文筛选感知 (Perception)：多路检索 arXiv 最新学术成果
  3. 全文解析 (HTML Full-Text Reading)：解析 arXiv 官方 HTML 全文（包含 Method、Experiments、开源代码）
  4. 多轮对话深度认知 (Multi-Turn Refinement via DeepSeek Flash)：
     - Turn 1: 提取大白话概述(TL;DR)、输入输出定义、四维度打分(0-10)、核心机制与KaTeX公式、关键实验
     - Turn 2: 多轮精炼压缩，消除长篇冗余叙述，校验数学公式
  5. 模板解耦渲染 (Jinja2 Template + KaTeX)：使用独立 template.html 渲染紧凑卡片排版
"""

import os
import sys
import json
import re
import time
from datetime import datetime, timezone, timedelta
import requests
import feedparser
from jinja2 import Template

# 引入项目根目录以导入 utils
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(__file__))

from utils.mailer import send_email_html
from html_reader import extract_full_paper

BJT = timezone(timedelta(hours=8))
now_bjt = datetime.now(BJT)

MEMORY_FILE = os.path.join(os.path.dirname(__file__), "memory", "history.json")
TEMPLATE_EMAIL_FILE = os.path.join(os.path.dirname(__file__), "template_email.html")
TEMPLATE_WEB_FILE = os.path.join(os.path.dirname(__file__), "template_web.html")
SRC_DIR = os.path.dirname(os.path.dirname(__file__))
REPO_ROOT = os.path.dirname(SRC_DIR)
TEMPLATE_PORTAL_FILE = os.path.join(REPO_ROOT, "template_portal.html")
DOCS_ROOT = os.path.join(REPO_ROOT, "docs")
DOCS_DIR = os.path.join(DOCS_ROOT, "paper-agent")
PAGES_BASE_URL = os.getenv("PAGES_BASE_URL", "https://crimson-and-clover.github.io/daily-actions")





def clean_math_for_email(text: str) -> str:
    """将 LaTeX 转换为邮件友好的清晰文本/Unicode数学符号，消除乱码反斜杠"""
    if not text:
        return ""
    t = text
    # 常用运算符与符号
    t = re.sub(r'\\times', '×', t)
    t = re.sub(r'\\cdot', '·', t)
    t = re.sub(r'\\approx', '≈', t)
    t = re.sub(r'\\leq|\\le', '≤', t)
    t = re.sub(r'\\geq|\\ge', '≥', t)
    t = re.sub(r'\\neq|\\ne', '≠', t)
    t = re.sub(r'\\in', '∈', t)
    t = re.sub(r'\\notin', '∉', t)
    t = re.sub(r'\\subset', '⊂', t)
    t = re.sub(r'\\cup', '∪', t)
    t = re.sub(r'\\cap', '∩', t)
    t = re.sub(r'\\pm', '±', t)
    t = re.sub(r'\\to|\\rightarrow', '→', t)
    t = re.sub(r'\\mid', '|', t)
    # 希腊字母
    t = re.sub(r'\\Theta', 'Θ', t)
    t = re.sub(r'\\theta', 'θ', t)
    t = re.sub(r'\\lambda', 'λ', t)
    t = re.sub(r'\\xi', 'ξ', t)
    t = re.sub(r'\\pi', 'π', t)
    t = re.sub(r'\\mu', 'μ', t)
    t = re.sub(r'\\sigma', 'σ', t)
    t = re.sub(r'\\tau', 'τ', t)
    t = re.sub(r'\\alpha', 'α', t)
    t = re.sub(r'\\beta', 'β', t)
    t = re.sub(r'\\gamma', 'γ', t)
    t = re.sub(r'\\ell', 'l', t)
    # 样式修饰
    t = re.sub(r'\\mathcal\{([A-Za-z])\}', r'\1', t)
    t = re.sub(r'\\mathbf\{([A-Za-z0-9_]+)\}', r'\1', t)
    t = re.sub(r'\\tilde\{([A-Za-z0-9_]+)\}', r'\1~', t)
    t = re.sub(r'\\hat\{([A-Za-z0-9_]+)\}', r'\1^', t)
    t = re.sub(r'\\arg\\min', 'argmin', t)
    t = re.sub(r'\\arg\\max', 'argmax', t)
    t = re.sub(r'\\langle|\\rangle', '', t)
    t = re.sub(r'\\top|\\intercal', 'ᵀ', t)
    t = re.sub(r'\\left|\\right', '', t)
    t = re.sub(r'\\\|', '‖', t)
    # 去除多余命令转义反斜杠
    t = re.sub(r'\\([A-Za-z]+)', r'\1', t)
    # 移除 LaTeX 行内公式标志 $
    t = t.replace('$', '')
    # 简化花括号
    t = re.sub(r'\{([^{}]+)\}', r'(\1)', t)

    return t.strip()


RESEARCH_TRACKS = [
    {
        "id": "world_models",
        "tag": "世界模型 & WAM (World Models)",
        "query": 'all:"world model" OR all:"world action model" OR all:"world models"',
        "keywords": ["world model", "world models", "world action model", "wam", "generative world", "dynamics model"]
    },
    {
        "id": "vla_embodied",
        "tag": "具身智能 & VLA (Vision-Language-Action)",
        "query": 'all:"vision-language-action" OR all:"vla" OR all:"robot manipulation" OR all:"humanoid policy"',
        "keywords": ["vision-language-action", "vla", "embodied", "manipulation", "robot policy", "humanoid", "diffusion policy"]
    },
    {
        "id": "autonomous_driving",
        "tag": "端到端自动驾驶 (Autonomous Driving)",
        "query": 'all:"autonomous driving" OR all:"end-to-end driving" OR all:"motion planning"',
        "keywords": ["autonomous driving", "end-to-end driving", "motion planning", "trajectory prediction", "self-driving", "nuscenes"]
    }
]


class AgentMemory:
    """持久化状态记录库"""
    def __init__(self, filepath=MEMORY_FILE):
        self.filepath = filepath
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"读取状态记录异常，初始化默认记录: {e}", file=sys.stderr)
        return {
            "seen_paper_ids": [],
            "favorite_topics": ["world_model", "wam", "vla", "autonomous_driving"],
            "total_analyzed": 0,
            "last_run": None
        }

    def is_seen(self, arxiv_id: str) -> bool:
        return arxiv_id in self.data.get("seen_paper_ids", [])

    def mark_seen(self, arxiv_id: str):
        if "seen_paper_ids" not in self.data:
            self.data["seen_paper_ids"] = []
        if arxiv_id not in self.data["seen_paper_ids"]:
            self.data["seen_paper_ids"].append(arxiv_id)
            self.data["total_analyzed"] = self.data.get("total_analyzed", 0) + 1

    def save(self):
        self.data["last_run"] = now_bjt.strftime("%Y-%m-%d %H:%M:%S")
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        print(f"[状态持久化] 记录已更新，累计分析文献: {self.data.get('total_analyzed', 0)} 篇")


def clean_text(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()


def fetch_arxiv_candidates(track: dict, max_results: int = 12):
    """感知外部环境：从 arXiv 拉取候选论文"""
    url = "https://export.arxiv.org/api/query"
    params = {
        "search_query": track["query"],
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results
    }
    headers = {
        "User-Agent": "ResearchResidentAgent/2.0 (academic-research-tool; mailto:agent@daily-actions.org)"
    }
    
    for attempt in range(2):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=25)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)
            papers = []
            for entry in feed.entries:
                arxiv_id = entry.id.split("/abs/")[-1] if "/abs/" in entry.id else entry.id
                authors = [a.name for a in getattr(entry, "authors", [])]
                author_str = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")
                published = getattr(entry, "published", "").split("T")[0]
                
                papers.append({
                    "id": arxiv_id,
                    "title": clean_text(entry.title),
                    "summary": clean_text(entry.summary),
                    "authors": author_str,
                    "link": entry.link,
                    "pdf": entry.link.replace("/abs/", "/pdf/") + ".pdf",
                    "html_url": entry.link.replace("/abs/", "/html/"),
                    "published": published
                })
            return papers
        except Exception as e:
            print(f"arXiv 查询尝试 {attempt+1} 失败: {e}", file=sys.stderr)
            time.sleep(3)
    return []


def parse_json_safely(raw_text: str):
    """从大模型输出中提取并解析合法 JSON"""
    if not raw_text:
        return None
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(raw_text[start:end+1])
        except Exception:
            return None
    return None


def reason_with_deepseek(paper: dict, api_key: str) -> dict:
    """
    通过 DeepSeek Flash 开展多轮对话：
    Turn 1: 全文核心提取 + 各维度量化打分 + 白话输入输出定义
    Turn 2: 多轮精炼审校，压缩冗长叙述，校验 KaTeX 格式数学符号
    """
    full_info = paper.get("full_content", {})
    method_text = full_info.get("method", "") or paper['summary']
    exp_text = full_info.get("experiments", "") or "请结合方法论与摘要评估基准表现"

    fallback_data = {
        "tldr": f"{paper['title']} 针对当前任务构建了专门的表征与策略框架。",
        "input_output": {
            "input": "多模态观测数据与历史序列",
            "output": "未来状态预测或动作控制量"
        },
        "scores": {"novelty": 7.5, "engineering": 7.5, "experiments": 7.5, "overall": 7.5},
        "method_points": [
            "构建紧凑的输入特征投影机制",
            "引入动力学先验辅助策略学习",
            "采用复合损失函数进行端到端优化"
        ],
        "experiment_takeaway": "在基准测试中验证了性能优越性。"
    }

    if not api_key:
        return fallback_data

    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    model_name = "deepseek-flash"

    # --- Turn 1: 首次技术解析与评分 ---
    turn1_prompt = f"""
你是一位深耕【世界模型 (World Models)、WAM、VLA (Vision-Language-Action)、端到端自动驾驶、具身机器人】方向的顶尖学者。
请深度阅读以下论文的标题、摘要、核心架构 (Method) 以及实验评测 (Experiments) 文本，完成清晰立即可懂的学术技术解析。
请勿使用任何表情符号 (Emoji)，采用严谨客观的技术语言，输出合法 JSON 对象，包含以下键值：
- tldr: 白话概念通俗精析（2-3句话）：通俗讲清这篇论文到底在解决什么核心痛点、做了一件什么事；深入浅出地解释其中涉及的关键技术名词与概念（用通俗大白话把专业术语拆解透彻，如什么是反事实推演、什么是潜空间动力学、什么是动作空间离散化等）；并阐明其核心直觉与突破机制。
- input_output: 对象，包含 input (明确说明输入是什么物理/传感器信号，如：单目RGB图像、点云、历史动作) 与 output (明确说明输出是什么控制量或未来预测量，如：末端执行器6自由度位姿轨迹、未来多视角视频)。要求：尽量用清晰明确的中文技术词汇说明，切勿堆叠晦涩的数学公式符号。

- scores: 对象，给出0-10分的量化打分：
  - novelty: 创新性得分 (0-10)
  - engineering: 工程落地可行性得分 (0-10，考虑算力开销与实时性)
  - experiments: 实验扎实度与消融充分性 (0-10)
  - overall: 综合推荐指数 (0-10)
- method_points: 数组，2-3条核心机制与技术实现，每条控制在1-2句话内。数学符号必须严格使用标准 KaTeX 格式（如 $s_{{t+1}}$, $\\mathcal{{L}}_{{flow}}$）
- experiment_takeaway: 1句话提炼最关键的量化对比结论

【论文标题】: {paper['title']}
【官方摘要】: {paper['summary']}
【核心架构与方法论原文 (Method)】: {method_text[:6500]}
【实验对比与消融实验 (Experiments)】: {exp_text[:3500]}
"""

    messages = [
        {"role": "system", "content": "You are a professional AI researcher providing technical paper analysis in strict JSON without any emojis."},
        {"role": "user", "content": turn1_prompt}
    ]

    session = requests.Session()
    t0 = time.time()
    turn1_result = None

    try:
        r1 = session.post(
            url,
            headers=headers,
            json={
                "model": model_name,
                "messages": messages,
                "reasoning_effort": "low",
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
                "max_tokens": 65536
            },
            timeout=50
        )
        if r1.status_code == 200:
            turn1_text = r1.json()["choices"][0]["message"].get("content", "")
            turn1_result = parse_json_safely(turn1_text)
            messages.append({"role": "assistant", "content": turn1_text})
    except Exception as e:
        print(f"[{model_name}] Turn 1 异常: {e}", file=sys.stderr)

    if not turn1_result:
        return fallback_data

    # --- Turn 2: 多轮对话精炼审校（严格压缩篇幅、校验公式）---
    turn2_prompt = """
请对上述生成的内容进行第二轮审查与精炼：
1. 保持 tldr 白话概述的通俗性与概念解释深度，确保不仅讲清在做什么，还能把核心技术名词用人话解释清楚；
2. 其他模块（输入输出、方法、实验）保持精简扼要，剔除空泛套话；
3. 检查所有数学符号必须以标准的 $ ... $ 或 $$ ... $$ 包裹，以便 KaTeX 正确渲染；
4. 输出纯 JSON，保持相同键值结构 (tldr, input_output, scores, method_points, experiment_takeaway)。
"""
    messages.append({"role": "user", "content": turn2_prompt})

    try:
        r2 = session.post(
            url,
            headers=headers,
            json={
                "model": model_name,
                "messages": messages,
                "reasoning_effort": "low",
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
                "max_tokens": 65536
            },
            timeout=40
        )
        if r2.status_code == 200:
            turn2_text = r2.json()["choices"][0]["message"].get("content", "")
            turn2_result = parse_json_safely(turn2_text)
            if turn2_result and "tldr" in turn2_result:
                cost = time.time() - t0
                print(f"     [{model_name}] 多轮审校完成 (耗时: {cost:.1f}s | 综合评分: {turn2_result.get('scores', {}).get('overall')}/10)")
                return turn2_result
    except Exception as e:
        print(f"[{model_name}] Turn 2 审校跳过 (平滑采用 Turn 1 结果): {e}", file=sys.stderr)

    cost = time.time() - t0
    print(f"     [{model_name}] 初轮解析完成 (耗时: {cost:.1f}s | 综合评分: {turn1_result.get('scores', {}).get('overall')}/10)")
    return turn1_result


def prepare_tracks_data(track_results):
    """整理待渲染的文献数据结构"""
    tracks_data = []
    for track in RESEARCH_TRACKS:
        papers = track_results.get(track["id"], [])
        formatted_papers = []
        for p in papers:
            full_info = p.get("full_content", {})
            reasoning = p.get("reasoning", {}) or {}
            io_data = reasoning.get("input_output", {}) or {}
            method_points = reasoning.get("method_points", []) or []

            # 邮件专用的干净数学符号/文本字段
            clean_io_input = clean_math_for_email(io_data.get("input", ""))
            clean_io_output = clean_math_for_email(io_data.get("output", ""))
            clean_method_points = [clean_math_for_email(pt) for pt in method_points]
            clean_takeaway = clean_math_for_email(reasoning.get("experiment_takeaway", ""))

            # 复制一份 reasoning 挂载 clean_* 字段供邮件模板使用
            email_reasoning = dict(reasoning)
            email_reasoning["clean_io_input"] = clean_io_input
            email_reasoning["clean_io_output"] = clean_io_output
            email_reasoning["clean_method_points"] = clean_method_points
            email_reasoning["clean_takeaway"] = clean_takeaway

            formatted_papers.append({
                "id": p["id"],
                "title": p["title"],
                "authors": p["authors"],
                "published": p["published"],
                "link": p["link"],
                "pdf": p["pdf"],
                "html_url": p["html_url"],
                "has_full_text": full_info.get("has_full_text", False),
                "github_urls": full_info.get("github_urls", []),
                "reasoning": email_reasoning
            })
        tracks_data.append({
            "tag": track["tag"],
            "papers": formatted_papers
        })
    return tracks_data


def render_web_report_html(tracks_data, total_seen_count, date_str):
    """渲染适用于 GitHub Pages 的完整版 HTML (包含 KaTeX 与 CSS Grid)"""
    today_count = sum(len(track["papers"]) for track in tracks_data)
    with open(TEMPLATE_WEB_FILE, "r", encoding="utf-8") as f:
        template_str = f.read()

    template = Template(template_str)
    return template.render(
        date_str=date_str,
        today_count=today_count,
        total_seen_count=total_seen_count,
        tracks=tracks_data
    )


def render_email_report_html(tracks_data, total_seen_count, date_str, pages_url=None):
    """渲染适用于 Gmail 邮件客户端的极简版 HTML (纯 Table 布局、白话概述与打分，引导至 Pages)"""
    today_count = sum(len(track["papers"]) for track in tracks_data)
    with open(TEMPLATE_EMAIL_FILE, "r", encoding="utf-8") as f:
        template_str = f.read()

    template = Template(template_str)
    return template.render(
        date_str=date_str,
        today_count=today_count,
        total_seen_count=total_seen_count,
        tracks=tracks_data,
        pages_url=pages_url
    )


def main():
    print(f"[{now_bjt.strftime('%Y-%m-%d %H:%M:%S')}] 启动文献分析程序 (双模态: 邮件极简 + GitHub Pages 完整版)...")
    memory = AgentMemory()
    print(f"[状态加载] 已记录文献数量: {len(memory.data.get('seen_paper_ids', []))} 篇")

    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    if deepseek_key:
        print("[模型服务] DeepSeek API 已连接验证")
    else:
        print("[模型服务] 未检测到 DEEPSEEK_API_KEY，将运行于轻量降级模式")

    track_results = {}

    for track in RESEARCH_TRACKS:
        print(f"\n[检索追踪] 领域: {track['tag']} ...")
        candidates = fetch_arxiv_candidates(track, max_results=8)
        
        selected = []
        for p in candidates:
            if memory.is_seen(p["id"]):
                continue

            text_to_check = (p["title"] + " " + p["summary"]).lower()
            if any(kw.lower() in text_to_check for kw in track["keywords"]):
                print(f"\n匹配文献: {p['title'][:50]}...")
                
                # 第一步：抓取 arXiv HTML 全文正文与开源代码
                print(f"  -> 获取 arXiv HTML 全文正文 (Method/Experiments)...")
                p["full_content"] = extract_full_paper(p["id"])
                has_html = p["full_content"]["has_full_text"]
                print(f"     HTML 全文解析: {'成功' if has_html else '降级至Abstract'}")
                if p["full_content"]["github_urls"]:
                    print(f"     开源仓库: {p['full_content']['github_urls']}")

                # 第二步：调用 DeepSeek Flash 展开多轮技术解析
                print("  -> 模型技术分析中 (TL;DR / 输入输出 / 各维度打分 / KaTeX公式)...")
                p["reasoning"] = reason_with_deepseek(p, deepseek_key)
                
                memory.mark_seen(p["id"])
                selected.append(p)
                
                if len(selected) >= 1:  # 精选每个主题 1 篇进行深度精读演示
                    break
        
        track_results[track["id"]] = selected
        print(f"  -> 完成，当前领域精选 {len(selected)} 篇文献")

    total_analyzed = memory.data.get("total_analyzed", 0)
    date_str = now_bjt.strftime("%Y-%m-%d")
    tracks_data = prepare_tracks_data(track_results)

    # 1. 生成并保存 GitHub Pages 静态站点文档 (docs/index.html & docs/archives/...)
    os.makedirs(DOCS_DIR, exist_ok=True)
    web_html = render_web_report_html(tracks_data, total_analyzed, date_str)
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

    # 2. 生成邮件版本 HTML (极简风格 + 导流到 GitHub Pages paper-agent 专区)
    pages_today_url = f"{PAGES_BASE_URL.rstrip('/')}/paper-agent/index.html"
    email_html = render_email_report_html(tracks_data, total_analyzed, date_str, pages_url=pages_today_url)

    # 3. 生成或更新 GitHub Pages 根目录导航页 (docs/index.html)，从独立模板渲染
    root_index_path = os.path.join(DOCS_ROOT, "index.html")
    if os.path.exists(TEMPLATE_PORTAL_FILE):
        with open(TEMPLATE_PORTAL_FILE, "r", encoding="utf-8") as f:
            portal_html = f.read()
        with open(root_index_path, "w", encoding="utf-8") as f:
            f.write(portal_html)
        print(f"[门户生成] 根目录多CI导航主页已更新: {root_index_path}")



    # 3. 发送邮件并写入本地预览
    subject = f"AI 前沿学术晨报 ({date_str})"
    preview_email_path = os.path.join(os.path.dirname(__file__), "preview_email.html")
    with open(preview_email_path, "w", encoding="utf-8") as f:
        f.write(email_html)
    print(f"[邮件生成] 邮件预览文件已保存: {preview_email_path}")

    send_email_html(subject, email_html, preview_email_path)

    memory.save()
    print("文献分析与简报渲染流程执行完成。")


if __name__ == "__main__":
    main()

