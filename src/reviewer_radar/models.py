"""
Reviewer Radar 强类型实体数据模型 (Domain Models)
杜绝无类型 Dict 传递，统一数据契约
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class ConferencePhase(StrEnum):
    """顶会生命周期所处阶段"""

    PRE_DEADLINE = "PRE_DEADLINE"  # 截稿前预热 (主会与 Workshop Reviewer 密集招募期)
    ACTIVE_REVIEW = "ACTIVE_REVIEW"  # 正审与救火期 (Emergency Reviewer 高发期)
    REBUTTAL_DECISION = "REBUTTAL_DECISION"  # 答辩与录用期
    CONCLUDED = "CONCLUDED"  # 已闭幕


class ConferenceTarget(BaseModel):
    """经过 CCF-DDL 时程推导的高价值目标顶会实体"""

    title: str = Field(description="会议名称，如 CVPR, ICLR")
    year: int = Field(description="会议所属年份，如 2027")
    ccf_rank: str = Field(default="A", description="CCF 评级: A / B")
    deadline: str = Field(description="投稿截止日期 (YYYY-MM-DD)")
    rebuttal_deadline: str | None = Field(default=None, description="答辩截止日期 (YYYY-MM-DD)")
    diff_days: int = Field(description="相对当前基准时间的天数差 (负数为即将截稿，正数为截稿后)")
    phase: ConferencePhase = Field(description="当前所处的生命周期阶段")
    phase_label_zh: str = Field(description="阶段中文说明，如 '⏰ 即将截稿 (招募启动中)'")
    official_url: str = Field(description="该年度官方主页入口")
    openreview_prefix: str | None = Field(default=None, description="OpenReview Venue 前缀标识")


class WebLinkItem(BaseModel):
    """网页提取的外链实体"""

    text: str = Field(description="链接锚文本")
    url: str = Field(description="完整标准化的绝对 URL")


class PageContentExtract(BaseModel):
    """网页正文提取与特征嗅探实体"""

    url: str = Field(description="目标网页 URL")
    title: str = Field(description="网页标题")
    text_snippet: str = Field(description="降噪后的核心文本片段 (截取前 N 字符)")
    detected_forms: list[str] = Field(default_factory=list, description="嗅探到的内嵌表单链接 (Google Form / MS Form 等)")
    detected_emails: list[str] = Field(default_factory=list, description="嗅探到的联系邮箱")


class ReviewerOpportunity(BaseModel):
    """结构化审稿人招募机会实体 (用于入库与邮件通知)"""

    conference_name: str = Field(description="会议/Workshop 规范全称与年份")
    form_url: str = Field(description="申请表单或官方入口链接")
    recruitment_type: str = Field(description="招募类型: 常规招募 (Call for Reviewers) 或 紧急救火 (Emergency Reviewers)")
    deadline: str = Field(description="截止时间说明")
    contact_email: str | None = Field(default=None, description="组织者或 Chair 联系邮箱")
    research_fields: list[str] = Field(default_factory=list, description="匹配的研究方向标签")
    summary_zh: str = Field(description="中文简评，重点说明该机会的学术含金量与要求")
    pitch_template_en: str = Field(description="为学者量身定制的地道英文自荐信 (Bio & Pitch)")
    source_url: str | None = Field(default=None, description="发现该机会的原始网页或专场主页")
