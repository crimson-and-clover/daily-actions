"""
基于 DeepSeek 的审稿机会智能研判与自荐信生成器
严格剔除无关 Call for Papers，提炼表单与截止时间，并为 NIW 申请者生成专属自荐模板
"""

import json

from openai import OpenAI

from reviewer_radar.config import DEEPSEEK_API_KEY, USER_ACADEMIC_PROFILE


def get_deepseek_client() -> OpenAI:
    """初始化 DeepSeek 客户端 (OpenAI 兼容协议)"""
    return OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
    )


ANALYZER_SYSTEM_PROMPT = """你是一名资深计算机视觉与人工智能领域的顶级学者兼美国 NIW 移民审稿专家。
你的任务是严格审查抓取到的学术会议/Workshop/平台信息，完成两项核心工作：
1. 【精准研判】：
   - 必须严格区分 "Call for Reviewers / Emergency Reviewers"（审稿人招募/救火）与 "Call for Papers"（论文投稿征文）。
   - 只有确认是【招募审稿人】的信息才判定为有效（is_valid: true）。
   - 提取真实的申请表单链接 (Google Form / MS Form / OpenReview)、截止日期、涉及方向。

2. 【定制自荐信 (Bio & Pitch)】：
   - 申请人背景：在计算机视觉顶会 ICCV、CVPR 发表过学术论文，主攻计算机视觉、多模态与深度学习方向。
   - 目标：申请担任该会议/Workshop 的 Reviewer（用于积累高质量同行评审经验与 NIW 证据）。
   - 撰写一段纯正、地道、极具说服力的英文自荐信（约 80-120 词），包含其顶会发表资历和按时提交高标准评审的承诺，方便申请人直接复制粘贴进申请表单。

请务必以合法的 JSON 格式返回，JSON 结构如下：
{
  "is_valid": true/false,
  "confidence_score": 0.0 - 1.0,
  "conference_name": "简明会议名称及年份",
  "recruitment_type": "常规招募 (Call for Reviewers) / 紧急救火 (Emergency Reviewers)",
  "form_url": "最终用于申请的有效链接",
  "deadline": "截止时间或说明 (无则填 '尽快申请/招满即止')",
  "research_fields": ["匹配的研究方向列表"],
  "summary_zh": "关于此次招募的中文简明说明 (重点突出对 NIW 的价值)",
  "pitch_template_en": "为申请人量身生成的英文自荐信"
}
"""


def analyze_and_generate_pitch(raw_opp: dict) -> dict | None:
    """调用 DeepSeek 进行语义深度校验并生成量身定制的自荐信"""
    if not DEEPSEEK_API_KEY:
        print("⚠️ 未配置 DEEPSEEK_API_KEY，跳过大模型语义增强，返回基础信息")
        return {
            "is_valid": True,
            "confidence_score": 0.8,
            "conference_name": raw_opp.get("conference", "Top Conference"),
            "recruitment_type": raw_opp.get("type", "Reviewer Recruitment"),
            "form_url": raw_opp.get("form_url", raw_opp.get("source_url")),
            "deadline": "请查阅原页面",
            "research_fields": USER_ACADEMIC_PROFILE["expertise"],
            "summary_zh": f"在 {raw_opp.get('conference')} 检测到审稿人申请入口",
            "pitch_template_en": (
                "Dear Program Chairs,\n\n"
                "I am writing to express my strong interest in serving as a reviewer for your prestigious venue. "
                "I am an active researcher with publications in top-tier computer vision conferences (including CVPR and ICCV). "
                "My expertise covers Computer Vision, Multimodal Learning, and Generative Models. "
                "I am committed to providing constructive, timely, and high-quality reviews.\n\n"
                "Thank you for considering my application."
            ),
        }

    client = get_deepseek_client()

    profile_info = []
    if USER_ACADEMIC_PROFILE.get("openreview_profile"):
        profile_info.append(f"申请人 OpenReview Profile: {USER_ACADEMIC_PROFILE['openreview_profile']}")
    if USER_ACADEMIC_PROFILE.get("google_scholar"):
        profile_info.append(f"申请人 Google Scholar: {USER_ACADEMIC_PROFILE['google_scholar']}")
    profile_str = ("\n" + "\n".join(profile_info)) if profile_info else ""

    user_content = f"""
请评估以下学术信息是否为真实有效的【审稿人招募/救火】：
会议名称: {raw_opp.get("conference")} ({raw_opp.get("full_name")})
标题: {raw_opp.get("title")}
来源网址: {raw_opp.get("source_url")}
提取到的表单链接: {raw_opp.get("form_url")}{profile_str}
页面上下文片段:
\"\"\"{raw_opp.get("context", "")[:800]}\"\"\"
"""

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": ANALYZER_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        content = response.choices[0].message.content or "{}"
        result = json.loads(content)

        if not result.get("is_valid", False):
            print(f"  ❌ [DeepSeek 过滤] 判定为非审稿招募 (可能是 Call for Papers): {raw_opp.get('title')}")
            return None

        # 合并原始与深度解析数据
        result["original_opp"] = raw_opp
        return result

    except Exception as e:
        print(f"❌ [DeepSeek] 研判过程发生异常: {e}")
        return None
