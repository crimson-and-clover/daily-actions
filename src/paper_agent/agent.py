"""
Resident Paper Agent (学术研究助理 Agent)
- 研究方向：
  1. 测试期训练 & 推理扩展 (Test-Time Training / Scaling)
  2. 后训练强化学习与机械可解释性 (Post-Training, RLHF & Interpretability)
  3. 流匹配与视频生成基础模型 (Flow Matching & Video Generation)
  4. 大模型推理与长上下文架构 (LLM Reasoning & Architecture)
  5. 世界模型 & WAM (World Models)
  6. 具身智能 & VLA (Vision-Language-Action)
  7. 端到端自动驾驶 (Autonomous Driving)
  8. 自动驾驶感知算法 (Autonomous Driving Perception)
- 运行机制：
  1. 长期状态记录 (State Tracking)：记录已分析论文 ID，去重过滤
  2. 论文筛选感知 (Perception)：多路检索 arXiv 最新学术成果
  3. 全文解析 (HTML Full-Text Reading)：解析 arXiv 官方 HTML 全文（包含 Method、Experiments、开源代码）
  4. 多轮对话深度认知 (Multi-Turn Refinement via DeepSeek Flash)：
     - Turn 1: 提取大白话概述(TL;DR)、输入输出定义、四维度打分(0-10)、核心机制与KaTeX公式、关键实验
     - Turn 2: 多轮精炼压缩，消除长篇冗余叙述，校验数学公式
  5. 模板解耦渲染 (Jinja2 Template + KaTeX)：渲染双模态研报（Web 完整版 + 邮件大白话精读）
"""

from pathlib import Path

from paper_agent.arxiv_client import fetch_arxiv_candidates
from paper_agent.config import (
    CANDIDATES_PER_TRACK,
    DEEPSEEK_API_KEY,
    DOCS_DIR,
    DOCS_ROOT,
    GMAIL_APP_PASS,
    GMAIL_USER,
    IS_CI,
    MAX_PAPERS_PER_TRACK,
    MIN_AUTHORITY_SCORE,
    MIN_OVERALL_SCORE,
    MIN_RELEVANCE_SCORE,
    MIN_SCREEN_RELEVANCE_SCORE,
    NOTIFICATION_EMAIL,
    PAGES_BASE_URL,
    RESEARCH_TRACKS,
    get_now_bjt,
    validate_config,
)
from paper_agent.html_reader import extract_full_paper
from paper_agent.memory import AgentMemory
from paper_agent.reasoner import quick_screen_abstract, reason_with_deepseek
from paper_agent.renderer import (
    prepare_tracks_data,
    render_email_report_html,
    render_web_report_html,
)
from utils.mailer import send_email_html
from utils.pages_builder import render_section_index, update_portal_index


def main():
    validate_config()
    now_dt = get_now_bjt()
    print(f"[{now_dt.strftime('%Y-%m-%d %H:%M:%S')}] 启动文献分析程序 (双模态: 邮件极简 + GitHub Pages 完整版)...")
    memory = AgentMemory()
    print(f"[状态加载] 已记录文献数量: {len(memory.data.get('seen_paper_ids', []))} 篇")
    print("[模型服务] DeepSeek API 已连接验证")

    track_results = {}

    for track in RESEARCH_TRACKS:
        print(f"\n[检索追踪] 领域: {track['tag']} (候选池规模: {CANDIDATES_PER_TRACK}, 精选上限: {MAX_PAPERS_PER_TRACK}) ...")
        candidates = fetch_arxiv_candidates(track, max_results=CANDIDATES_PER_TRACK)
        print(f"  -> arXiv API 成功返回候选文献 {len(candidates)} 篇")

        selected = []
        for p in candidates:
            if memory.is_seen(p["id"]):
                continue

            print(f"\n评估候选: {p['title'][:55]}...")

            # 阶段 1：利用 Abstract + Title 进行毫秒级大模型打分，由本地程序自主判定是否入选
            print(f"  [阶段1: Abstract 快速初筛] 正在评估是否属于【{track['tag'][:12]}】核心赛道...")
            screen_score, screen_reason = quick_screen_abstract(p, DEEPSEEK_API_KEY, track=track)
            is_pass = screen_score >= MIN_SCREEN_RELEVANCE_SCORE  # 本地自主判定核心门槛

            if not is_pass:
                print(f"  [初筛淘汰] 摘要相关性得分 {screen_score:.1f}/10 (低于阈值 {MIN_SCREEN_RELEVANCE_SCORE}) | 理由: {screen_reason}")
                memory.mark_seen(p["id"])
                continue
            print(f"  [初筛通过] 摘要相关性 {screen_score:.1f}/10 (达到阈值 {MIN_SCREEN_RELEVANCE_SCORE}) | 理由: {screen_reason}")

            # 阶段 2：初筛通过后，才抓取 arXiv HTML 全文正文、代码与机构 Affiliations
            print("  [阶段2: 获取 arXiv HTML 全文] (Method/Experiments/Affiliations)...")
            p["full_content"] = extract_full_paper(p["id"])
            has_html = p["full_content"]["has_full_text"]
            print(f"     HTML 全文解析: {'成功' if has_html else '降级至Abstract'}")
            if p["full_content"]["github_urls"]:
                print(f"     开源仓库: {p['full_content']['github_urls']}")

            # 阶段 3：调用 DeepSeek Flash 开展多轮深度技术解析、机构权威度与细粒度评分
            print("  [阶段3: 全文多轮深度研读] 机构评估、KaTeX公式提取与白话解析...")
            reasoning_res = reason_with_deepseek(p, DEEPSEEK_API_KEY, track=track)
            if not reasoning_res:
                print("  [跳过] 文献解析失败，放弃并尝试本赛道下一篇候选...")
                continue

            scores = reasoning_res.get("scores", {})
            relevance = float(scores.get("relevance", 10.0))
            authority = float(scores.get("authority", 10.0))
            overall = float(scores.get("overall", 10.0))
            institution = reasoning_res.get("institution", "未明确标注机构")
            score_reason = reasoning_res.get("score_reason", "").strip() or "未提供明确判定说明"

            print(f"     [评分反馈] 机构: {institution} | 权威度: {authority}/10 | 相关性: {relevance}/10 | 综合: {overall}/10")
            print(f"     [打分理由] {score_reason}")

            # 相关性、机构权威度与综合质量严格把关过滤
            if relevance < MIN_RELEVANCE_SCORE:
                print(f"  [过滤淘汰] 相关性得分 {relevance} 低于阈值 {MIN_RELEVANCE_SCORE} | 理由: {score_reason}")
                memory.mark_seen(p["id"])
                continue

            if authority < MIN_AUTHORITY_SCORE:
                print(f"  [过滤淘汰] 机构权威度得分 {authority} 低于阈值 {MIN_AUTHORITY_SCORE} | 理由: {score_reason}")
                memory.mark_seen(p["id"])
                continue

            if overall < MIN_OVERALL_SCORE:
                print(f"  [过滤淘汰] 综合质量得分 {overall} 低于阈值 {MIN_OVERALL_SCORE} | 理由: {score_reason}")
                memory.mark_seen(p["id"])
                continue

            p["reasoning"] = reasoning_res
            memory.mark_seen(p["id"])
            selected.append(p)
            print(f"  [✅ 成功入选] 当前赛道已精选 {len(selected)}/{MAX_PAPERS_PER_TRACK} 篇")

            if len(selected) >= MAX_PAPERS_PER_TRACK:
                print(f"  [赛道满额] 已达到本赛道精选上限 {MAX_PAPERS_PER_TRACK} 篇，完成检索。")
                break

        track_results[track["id"]] = selected
        print(f"  -> 赛道结算，当前领域最终精选 {len(selected)} 篇高分优质文献")

    total_analyzed = memory.data.get("total_analyzed", 0)
    date_str = now_dt.strftime("%Y-%m-%d")
    tracks_data = prepare_tracks_data(track_results)

    # 1. 保存当日研报详情页面到 archives/{date}.html
    archive_dir = DOCS_DIR / "archives"
    archive_dir.mkdir(parents=True, exist_ok=True)
    date_path = archive_dir / f"{date_str}.html"
    web_html = render_web_report_html(tracks_data, total_analyzed, date_str)
    date_path.write_text(web_html, encoding="utf-8")
    print(f"[网页生成] 研报正文已保存至归档: {date_path}")

    # 2. 渲染专区聚合索引页到 paper-agent/index.html
    section_index_html = render_section_index(
        title="AI 前沿学术研报",
        badge="CI: RESIDENT PAPER AGENT",
        description="测试期训练、流匹配、后训练与可解释性、世界模型及端到端自动驾驶的前沿精读与各维度量化评估。",
        latest_date=date_str,
        latest_title=f"AI 前沿学术研报 ({date_str})",
        archives_dir=archive_dir,
    )
    index_path = DOCS_DIR / "index.html"
    index_path.write_text(section_index_html, encoding="utf-8")
    print(f"[网页生成] 论文专区索引主页已更新: {index_path}")

    # 3. 生成邮件版本 HTML (指向专区索引或当日详情)
    pages_today_url = f"{PAGES_BASE_URL.rstrip('/')}/paper-agent/archives/{date_str}.html"
    email_html = render_email_report_html(tracks_data, total_analyzed, date_str, pages_url=pages_today_url)

    # 4. 生成或更新 GitHub Pages 根目录导航页 (docs/index.html)
    update_portal_index(DOCS_ROOT)

    # 5. 发送邮件并写入本地预览 (干练高信息密度，去除Emoji)
    today_paper_count = sum(len(track["papers"]) for track in tracks_data)
    active_track_tags = [t["tag"].split(" ")[0] for t in tracks_data if t["papers"]][:3]
    tracks_summary_str = "/".join(active_track_tags) if active_track_tags else "前沿精选"
    subject = f"[Paper Agent] {date_str} 学术前沿研报: 精选{today_paper_count}篇 ({tracks_summary_str})"
    preview_email_path = Path(__file__).resolve().parent / "preview_email.html"
    preview_email_path.write_text(email_html, encoding="utf-8")
    print(f"[邮件生成] 邮件预览文件已保存: {preview_email_path}")

    send_email_html(
        subject=subject,
        html_content=email_html,
        gmail_user=GMAIL_USER,
        gmail_pass=GMAIL_APP_PASS,
        receiver=NOTIFICATION_EMAIL,
        is_ci=IS_CI,
        preview_path=preview_email_path,
    )

    memory.save()
    print("文献分析与简报渲染流程执行完成。")


if __name__ == "__main__":
    main()
