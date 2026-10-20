"""
Jinja2 HTML 邮件渲染模块
为用户渲染精美、实用的审稿招募通知与 NIW 证据指南
"""

from jinja2 import Environment, FileSystemLoader

from reviewer_radar.config import TEMPLATES_HTML_DIR


def render_reviewer_email(opportunities: list[dict], run_time_bjt: str) -> str:
    """渲染审稿雷达专属 HTML 邮件内容"""
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_HTML_DIR),
        autoescape=True,
    )
    template = env.get_template("reviewer_radar.html")
    return template.render(
        opportunities=opportunities,
        run_time_bjt=run_time_bjt,
    )
