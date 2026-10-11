"""
Paper Agent 配置与路径定义
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from utils.timezone import get_now_bjt

load_dotenv()

__all__ = [
    "CANDIDATES_PER_TRACK",
    "DEEPSEEK_API_KEY",
    "DOCS_DIR",
    "DOCS_ROOT",
    "GMAIL_APP_PASS",
    "GMAIL_USER",
    "IS_CI",
    "MAX_PAPERS_PER_TRACK",
    "MEMORY_FILE",
    "MIN_AUTHORITY_SCORE",
    "MIN_OVERALL_SCORE",
    "MIN_RELEVANCE_SCORE",
    "MIN_SCREEN_RELEVANCE_SCORE",
    "NOTIFICATION_EMAIL",
    "PAGES_BASE_URL",
    "RESEARCH_TRACKS",
    "TEMPLATES_HTML_DIR",
    "get_now_bjt",
    "validate_config",
]

# 环境变量与外部配置
GMAIL_USER = (os.getenv("GMAIL_USER") or "").strip()
GMAIL_APP_PASS = (os.getenv("GMAIL_APP_PASS") or "").replace(" ", "").strip()
NOTIFICATION_EMAIL = (os.getenv("NOTIFICATION_EMAIL") or "").strip() or GMAIL_USER
IS_CI = bool(os.getenv("CI"))
DEEPSEEK_API_KEY = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
PAGES_BASE_URL = os.getenv("PAGES_BASE_URL", "https://crimson-and-clover.github.io/daily-actions")


def validate_config() -> None:
    """运行前校验所有核心配置与环境变量"""
    errors = []
    if not DEEPSEEK_API_KEY:
        errors.append("未配置 DEEPSEEK_API_KEY，学术研报精读必须配置大模型密钥")
    if IS_CI:
        if not GMAIL_USER:
            errors.append("CI 环境中必须配置 GMAIL_USER 邮箱 Secrets")
        if not GMAIL_APP_PASS:
            errors.append("CI 环境中必须配置 GMAIL_APP_PASS 应用密码 Secrets")

    if errors:
        for err in errors:
            print(f"❌ [Paper Agent 配置错误] {err}", file=sys.stderr)
        sys.exit(1)


# 路径定位
CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CURRENT_DIR.parent.parent

# 状态与持久化路径 (统一存储于 state/paper-agent)
MEMORY_FILE = REPO_ROOT / "state" / "paper-agent" / "history.json"

# 模板路径
TEMPLATES_HTML_DIR = Path(__file__).resolve().parent / "templates" / "html"

# 文档与静态发布目录
DOCS_ROOT = REPO_ROOT / "docs"
DOCS_DIR = DOCS_ROOT / "paper-agent"

# 质量、相关性与机构权威度过滤阈值 (0-10 分制)
MIN_SCREEN_RELEVANCE_SCORE = 6.5  # 阶段 1：Abstract 快速初筛相关性门槛 (由程序自己判定是否入选阶段 2)
MIN_RELEVANCE_SCORE = 7.0  # 阶段 3：全文深度精读相关性基准阈值 (低于此分数的弱相关/边缘应用论文将被淘汰)
MIN_AUTHORITY_SCORE = 5.0  # 学校实验室/机构权威度门槛 (评估作者与实验室背景公信力，淘汰低质水文)
MIN_OVERALL_SCORE = 6.5  # 综合推荐指数基准阈值

# 赛道抓取与入选容量配置
CANDIDATES_PER_TRACK = 25  # 每个赛道初始感知候选池规模 (放大到 25 篇)
MAX_PAPERS_PER_TRACK = 3  # 每个赛道精选入选上限 (控制为 3 篇高质量文献)

# 研究追踪轨道定义 (精简Query表达式，由大模型负责深层语义把关)
RESEARCH_TRACKS = [
    {
        "id": "ttt_inference",
        "tag": "测试期训练 & 推理扩展 (Test-Time Training / Scaling)",
        "query": '(cat:cs.LG OR cat:cs.AI OR cat:cs.CL) AND ("test-time training" OR "test-time compute" OR "inference scaling" OR "process reward" OR "test time compute")',
        "keywords": ["test-time training", "ttt", "test-time compute", "inference scaling", "o1", "process reward", "mcts reasoning", "chain-of-thought scaling", "test time compute"],
    },
    {
        "id": "post_training_interp",
        "tag": "后训练强化学习与机械可解释性 (Post-Training, RLHF & Interpretability)",
        "query": '(cat:cs.LG OR cat:cs.AI OR cat:cs.CL) AND (rlhf OR dpo OR rlaif OR "preference optimization" OR "mechanistic interpretability" OR "sparse autoencoder")',
        "keywords": ["rlhf", "dpo", "preference optimization", "rlaif", "mechanistic interpretability", "sparse autoencoder", "sae", "circuit analysis", "reinforcement learning from"],
    },
    {
        "id": "flow_matching_video",
        "tag": "流匹配与视频生成基础模型 (Flow Matching & Video Generation)",
        "query": '(cat:cs.CV OR cat:cs.LG OR cat:cs.AI) AND ("flow matching" OR "rectified flow" OR "video generation" OR "video diffusion" OR "world simulator")',
        "keywords": ["flow matching", "rectified flow", "video generation", "video diffusion", "consistent video", "continuous-time", "flow-based", "generative video"],
    },
    {
        "id": "llm_reasoning",
        "tag": "大模型推理与长上下文架构 (LLM Reasoning & Architecture)",
        "query": '(cat:cs.CL OR cat:cs.AI OR cat:cs.LG) AND ("reasoning model" OR "mathematical reasoning" OR "code generation" OR "long context" OR "state space model" OR mamba)',
        "keywords": ["reasoning model", "mathematical reasoning", "code generation", "long-context", "kv cache", "mamba", "state space model", "mixture-of-experts", "moe"],
    },
    {
        "id": "world_models",
        "tag": "世界模型 & WAM (World Models)",
        "query": '(cat:cs.AI OR cat:cs.RO OR cat:cs.CV OR cat:cs.LG) AND ("world model" OR "world models" OR "world action model" OR "dynamics model")',
        "keywords": ["world model", "world models", "world action model", "wam", "generative world", "dynamics model"],
    },
    {
        "id": "vla_embodied",
        "tag": "具身智能 & VLA (Vision-Language-Action)",
        "query": '(cat:cs.RO OR cat:cs.AI OR cat:cs.CV) AND ("vision-language-action" OR vla OR "robot manipulation" OR "humanoid policy" OR "diffusion policy")',
        "keywords": ["vision-language-action", "vla", "embodied", "manipulation", "robot policy", "humanoid", "diffusion policy"],
    },
    {
        "id": "autonomous_driving",
        "tag": "端到端自动驾驶 (Autonomous Driving)",
        "query": '(cat:cs.CV OR cat:cs.RO OR cat:cs.AI) AND ("autonomous driving" OR "end-to-end driving" OR "motion planning" OR "trajectory prediction")',
        "keywords": ["autonomous driving", "end-to-end driving", "motion planning", "trajectory prediction", "self-driving", "nuscenes"],
    },
    {
        "id": "ad_perception",
        "tag": "自动驾驶感知算法 (Autonomous Driving Perception)",
        "query": '(cat:cs.CV OR cat:cs.RO) AND ("3d object detection" OR "occupancy prediction" OR "bev perception" OR "point cloud" OR "camera-lidar fusion" OR "online mapping")',
        "keywords": ["3d object detection", "bev perception", "occupancy prediction", "point cloud", "camera-lidar fusion", "online mapping", "hd map", "occ", "lidar perception", "multi-view perception"],
    },
]
