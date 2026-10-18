"""
Reviewer Radar 原子工具集 (Tools Definition & Modular Dispatcher)
基于 Pydantic 强类型参数模型导出标准 OpenAI Tool Docs，杜绝无类型 Dict 混乱
"""

import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

import openai
import openreview
import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from reviewer_radar.ccf_timeline import get_active_conference_targets
from reviewer_radar.memory import RadarMemory
from reviewer_radar.models import PageContentExtract, ReviewerOpportunity, WebLinkItem

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )
}

# ==============================================================================
# 1. ToolContext 上下文载体
# ==============================================================================


@dataclass
class ToolContext:
    """Agent 执行期全局上下文状态"""

    memory: RadarMemory
    recorded_opportunities: list[ReviewerOpportunity] = field(default_factory=list)


# ==============================================================================
# 2. Pydantic 工具入参模型定义
# ==============================================================================


class GetActiveConferencesArgs(BaseModel):
    """查询当前日期下所有正处于【截稿前招募 / 正审救火 / Rebuttal】黄金窗口期的 CCF 顶会列表"""

    include_upcoming_days: int = Field(default=30, description="前瞻截稿天数，默认 30 天")


class FetchWebLinksArgs(BaseModel):
    """抓取指定顶会主页或 Workshop 列表页中的超链接 (自动规范化为绝对完整 URL)"""

    url: str = Field(description="目标网页 URL，如 https://cvpr.thecvf.com/Conferences/2027/Workshops")
    filter_keyword: str | None = Field(default=None, description="可选过滤关键词，如 'workshop', 'reviewer', 'call'")


class ReadPageContentArgs(BaseModel):
    """深入抓取目标网页的核心文本，并自动嗅探内嵌的表单外链 (Google Forms 等) 与联系邮箱"""

    url: str = Field(description="目标网页 URL，如具体 Workshop 主页或招募公告")
    max_chars: int = Field(default=3000, description="读取最大文本字符长度，默认 3000")


class SearchOpenReviewArgs(BaseModel):
    """在 OpenReview API 扫描指定顶会主会或 Workshop 专场的官方审稿人招募 (Recruitment) 邀请"""

    venue_prefix: str = Field(description="OpenReview Venue 前缀，例如 'thecvf.com/CVPR/2027' 或 'ICLR.cc/2027'")


class CheckIsAlreadyNotifiedArgs(BaseModel):
    """检查特定表单链接或机会 ID 是否已经在历史邮件中向用户推送过"""

    form_url: str = Field(description="表单或入口 URL")


class RecordReviewerOpportunityArgs(BaseModel):
    """登记确认有效的审稿人招募或救火机会，生成自荐信并加入推送简报"""

    conference_name: str = Field(description="会议/Workshop 规范全称与年份，如 CVPR 2027 Workshop on Autonomous Driving")
    form_url: str = Field(description="实际用于报名的表单链接或官方入口")
    recruitment_type: str = Field(description="招募性质: '常规招募 (Call for Reviewers)' 或 '紧急救火 (Emergency Reviewers)'")
    deadline: str = Field(description="申请截止时间说明 (无具体日期则填 '尽快申请/招满即止')")
    contact_email: str | None = Field(default=None, description="组织者或 Chair 联系邮箱")
    research_fields: list[str] = Field(default_factory=list, description="涉及的研究领域列表")
    summary_zh: str = Field(description="中文简评，阐明该机会的学术含金量与要求")
    pitch_template_en: str = Field(description="为学者量身定制的地道英文自荐信 (Bio & Pitch)")
    source_url: str | None = Field(default=None, description="发现该机会的原始专场页面")


# ==============================================================================
# 3. 工具底层执行逻辑 Handlers
# ==============================================================================


def _handle_get_active_conferences(args: GetActiveConferencesArgs, ctx: ToolContext) -> dict[str, Any]:
    targets = get_active_conference_targets()
    return {
        "status": "success",
        "count": len(targets),
        "conferences": [t.model_dump() for t in targets],
    }


def _handle_fetch_web_links(args: FetchWebLinksArgs, ctx: ToolContext) -> dict[str, Any]:
    url = args.url
    kw = (args.filter_keyword or "").lower().strip()
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return {"status": "error", "message": f"请求页面失败: HTTP {resp.status_code}"}
        soup = BeautifulSoup(resp.text, "html.parser")
        links: list[WebLinkItem] = []
        seen = set()

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:")):
                continue
            abs_url = urljoin(url, href)
            # 过滤非 HTTP 及二进制静态资源
            if not abs_url.startswith(("http://", "https://")):
                continue
            if any(abs_url.lower().endswith(ext) for ext in [".pdf", ".jpg", ".png", ".zip", ".tar.gz", ".css", ".js"]):
                continue
            text = a.get_text(separator=" ", strip=True)
            if kw and (kw not in href.lower() and kw not in text.lower()):
                continue
            if abs_url in seen:
                continue
            seen.add(abs_url)
            links.append(WebLinkItem(text=text[:80], url=abs_url))
            if len(links) >= 15:  # 严格防 Token 膨胀截断
                break

        return {
            "status": "success",
            "count": len(links),
            "links": [item.model_dump() for item in links],
        }
    except Exception as e:
        return {"status": "error", "message": f"抓取外链异常: {e}"}


def _handle_read_page_content(args: ReadPageContentArgs, ctx: ToolContext) -> dict[str, Any]:
    url = args.url
    max_chars = args.max_chars
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return {"status": "error", "message": f"请求正文失败: HTTP {resp.status_code}"}

        soup = BeautifulSoup(resp.text, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else ""

        # 剔除无用标签
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        raw_text = soup.get_text(separator=" ", strip=True)
        clean_snippet = re.sub(r"\s+", " ", raw_text)[:max_chars]

        # 嗅探内嵌表单
        detected_forms = set()
        form_patterns = [
            r"https?://(?:forms\.gle|docs\.google\.com/forms|forms\.office\.com|t\.co)/[^\s\"'<>]+",
        ]
        for pat in form_patterns:
            for match in re.findall(pat, resp.text):
                detected_forms.add(match)

        # 嗅探联系邮箱
        detected_emails = set()
        email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
        for em in re.findall(email_pattern, resp.text):
            if not any(ign in em.lower() for ign in ["example.com", "wixpress.com", "domain.com", "sentry.io", "github.com"]):
                detected_emails.add(em)

        extract = PageContentExtract(
            url=url,
            title=title,
            text_snippet=clean_snippet,
            detected_forms=list(detected_forms),
            detected_emails=list(detected_emails)[:4],
        )
        return {"status": "success", "data": extract.model_dump()}
    except Exception as e:
        return {"status": "error", "message": f"读取页面正文异常: {e}"}


def _handle_search_openreview(args: SearchOpenReviewArgs, ctx: ToolContext) -> dict[str, Any]:
    venue_prefix = args.venue_prefix.strip()
    try:
        client_v2 = openreview.api.OpenReviewClient(baseurl="https://api2.openreview.net")
    except Exception as e:
        return {"status": "error", "message": f"初始化 OpenReview 客户端失败: {e}"}

    found_invitations = []
    try:
        groups = client_v2.get_groups(prefix=venue_prefix)
        # 过滤主干
        candidate_groups = [
            g.id for g in groups
            if not any(k in g.id for k in ["Chairs", "Authors", "Track", "Proceedings", "Non-", "Proposals"])
        ][:4]  # 严格防 429 限流控制数量

        for gid in candidate_groups:
            invitation_id = f"{gid}/Reviewers/-/Recruitment"
            try:
                time.sleep(1.0)  # 严格遵守 OpenReview 20 req/min 限流控制
                inv = client_v2.get_invitation(invitation_id)
                if inv:
                    expdate = getattr(inv, "expdate", None)
                    found_invitations.append({
                        "venue_id": gid,
                        "invitation_id": invitation_id,
                        "expdate": expdate,
                        "group_url": f"https://openreview.net/group?id={gid}",
                    })
            except Exception:
                continue

        return {
            "status": "success",
            "count": len(found_invitations),
            "invitations": found_invitations,
        }
    except Exception as e:
        return {"status": "error", "message": f"检索 OpenReview 异常: {e}"}


def _handle_check_is_already_notified(args: CheckIsAlreadyNotifiedArgs, ctx: ToolContext) -> dict[str, Any]:
    url = args.form_url.strip().rstrip("/")
    is_notified = ctx.memory.is_notified(url)
    return {"status": "success", "form_url": url, "is_notified": is_notified}


def _handle_record_reviewer_opportunity(args: RecordReviewerOpportunityArgs, ctx: ToolContext) -> dict[str, Any]:
    opp = ReviewerOpportunity(
        conference_name=args.conference_name,
        form_url=args.form_url,
        recruitment_type=args.recruitment_type,
        deadline=args.deadline,
        contact_email=args.contact_email,
        research_fields=args.research_fields,
        summary_zh=args.summary_zh,
        pitch_template_en=args.pitch_template_en,
        source_url=args.source_url,
    )
    ctx.recorded_opportunities.append(opp)
    # 同步写入内存
    clean_url = opp.form_url.strip().rstrip("/")
    ctx.memory.record_notification(
        opp_id=clean_url,
        info={
            "conference_name": opp.conference_name,
            "recruitment_type": opp.recruitment_type,
            "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
    )
    return {
        "status": "success",
        "message": f"成功登记审稿机会: [{opp.conference_name}]，将在邮件简报中呈现",
        "total_recorded": len(ctx.recorded_opportunities),
    }


# ==============================================================================
# 4. 工具注册表与分发器
# ==============================================================================

TOOL_REGISTRY: dict[str, tuple[type[BaseModel], Any]] = {
    "get_active_conferences": (GetActiveConferencesArgs, _handle_get_active_conferences),
    "fetch_web_links": (FetchWebLinksArgs, _handle_fetch_web_links),
    "read_page_content": (ReadPageContentArgs, _handle_read_page_content),
    "search_openreview": (SearchOpenReviewArgs, _handle_search_openreview),
    "check_is_already_notified": (CheckIsAlreadyNotifiedArgs, _handle_check_is_already_notified),
    "record_reviewer_opportunity": (RecordReviewerOpportunityArgs, _handle_record_reviewer_opportunity),
}

AGENT_TOOLS: list[dict[str, Any]] = [
    openai.pydantic_function_tool(model_cls, name=name)
    for name, (model_cls, _) in TOOL_REGISTRY.items()
]


def execute_tool(fn_name: str, args: dict[str, Any] | BaseModel, context: ToolContext) -> dict[str, Any]:
    """统一分发并执行大模型发起的工具调用，入参经 Pydantic 模型严格强类型校验"""
    if fn_name not in TOOL_REGISTRY:
        return {"status": "error", "message": f"未知的工具名称: '{fn_name}'"}
    model_cls, handler = TOOL_REGISTRY[fn_name]
    try:
        validated_args = args if isinstance(args, model_cls) else model_cls.model_validate(args)
    except Exception as e:
        return {"status": "error", "message": f"参数校验失败: {e}"}
    try:
        return handler(validated_args, context)
    except Exception as e:
        return {"status": "error", "message": f"执行工具 '{fn_name}' 异常: {e}"}
