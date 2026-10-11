"""
Jinja2 模板加载与渲染核心模块 (Template Loader)
统一管理 Prompt 模板与 HTML 页面/邮件模板渲染
严格遵循 Fail-Fast 原则与模板环境缓存机制
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

# 仓库根目录与公共模板目录
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GLOBAL_TEMPLATES_DIR = REPO_ROOT / "templates"

_PROMPT_ENV_CACHE: dict[str, Environment] = {}
_HTML_ENV_CACHE: dict[str, Environment] = {}


def get_prompt_env(directory: Path) -> Environment:
    """获取 Prompt 专用的 Jinja2 环境（严格无静默缺失，不进行 HTML 实体转义）"""
    path_key = str(directory.resolve())
    if path_key not in _PROMPT_ENV_CACHE:
        env = Environment(
            loader=FileSystemLoader(path_key, encoding="utf-8"),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            autoescape=False,
        )
        _PROMPT_ENV_CACHE[path_key] = env
    return _PROMPT_ENV_CACHE[path_key]


def get_html_env(directory: Path) -> Environment:
    """获取 HTML 专用的 Jinja2 环境（支持 HTML 语法与模块内模板解析）"""
    path_key = str(directory.resolve())
    if path_key not in _HTML_ENV_CACHE:
        env = Environment(
            loader=FileSystemLoader(path_key, encoding="utf-8"),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        _HTML_ENV_CACHE[path_key] = env
    return _HTML_ENV_CACHE[path_key]


def render_prompt_template(template_dir: Path, template_name: str, **kwargs) -> str:
    """在指定 template_dir 下查找 Prompt 模板并渲染"""
    env = get_prompt_env(template_dir)
    template = env.get_template(template_name)
    return template.render(**kwargs).strip()


def render_html_template(template_dir: Path, template_name: str, **kwargs) -> str:
    """在指定 template_dir 下查找 HTML 模板并渲染"""
    env = get_html_env(template_dir)
    template = env.get_template(template_name)
    return template.render(**kwargs)


def render_global_html_template(template_name: str, **kwargs) -> str:
    """渲染全局共享模板 (templates/portal.html, templates/section_index.html)"""
    return render_html_template(GLOBAL_TEMPLATES_DIR, template_name, **kwargs)
