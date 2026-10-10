#!/usr/bin/env python3
from http.cookiejar import MozillaCookieJar
import json
import os
from pathlib import Path
from typing import Any, Dict

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
import base64
import dotenv

dotenv.load_dotenv()

# --- 配置区 ---
CHECKIN_URL = "https://glados.cloud/api/user/checkin"
EXCHANGE_URL = "https://glados.cloud/api/user/exchange"
REFERER_URL = "https://glados.cloud/console/checkin"
ORIGIN_URL = "https://glados.cloud"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def get_session(cookie_file: Path) -> requests.Session:
    """创建并配置支持自动重试的 Session"""
    session = requests.Session()

    # 配置重试策略
    # total: 总重试次数
    # backoff_factor: 退避频率，等待时间 = {backoff_factor} * (2 ** (retry_count - 1))
    # status_forcelist: 遇到以下状态码时强制重试
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["POST", "GET"]
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    # 加载 Cookies
    try:
        cookie_jar = MozillaCookieJar(str(cookie_file))
        cookie_jar.load(ignore_discard=True, ignore_expires=True)
        session.cookies.update(cookie_jar)
    except Exception as e:
        print(f"⚠️ 读取 Cookie 文件失败: {e}")

    # 设置通用 Headers
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Origin": ORIGIN_URL,
        "Referer": REFERER_URL,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
    })
    return session


def setup_cookies():
    """从环境变量解密并保存 Cookies"""
    script_dir = Path(__file__).parent
    cookie_path = script_dir / "glados_cookies.txt"
    cookies_text = base64.b64decode(
        os.getenv("COOKIES_GLADOS")).decode("utf-8")
    with cookie_path.open(mode="w", encoding="utf-8") as f:
        f.write(cookies_text)


def run_exchange() -> bool:
    script_dir = Path(__file__).parent
    cookie_path = script_dir / "glados_cookies.txt"
    if not cookie_path.exists():
        print(f"❌ 错误: 找不到 Cookie 文件 -> {cookie_path}")
        return False
    session = get_session(cookie_path)
    payload = {"planType": "plan500"}
    print("🚀 正在发起兑换请求...")
    try:
        response = session.post(EXCHANGE_URL, json=payload, timeout=15)
        response.raise_for_status()  # 如果状态码不是 200，直接抛出异常
        data = response.json()
        is_success = data.get("code") == 0
        days_added = data.get("daysAdded", 0)
        print(f"✅ 兑换请求完成！(增加 {days_added} 天)")
        return is_success
    except requests.exceptions.RequestException as e:
        print(f"❌ 网络请求异常: {e}")
    except json.JSONDecodeError:
        print(f"❌ 解析响应失败: 响应内容不是有效的 JSON\n{response.text}")
    return False


def run_checkin() -> bool:
    """执行签到逻辑"""
    script_dir = Path(__file__).parent
    cookie_path = script_dir / "glados_cookies.txt"
    if not cookie_path.exists():
        print(f"❌ 错误: 找不到 Cookie 文件 -> {cookie_path}")
        return False
    session = get_session(cookie_path)
    payload = {"token": "glados.cloud"}
    print("🚀 正在发起签到请求...")
    try:
        response = session.post(CHECKIN_URL, json=payload, timeout=15)
        response.raise_for_status()  # 如果状态码不是 200，直接抛出异常
        data = response.json()
        is_success, balance = analyze_result(data)
        return is_success, balance
    except requests.exceptions.RequestException as e:
        print(f"❌ 网络请求异常: {e}")
    except json.JSONDecodeError:
        print(f"❌ 解析响应失败: 响应内容不是有效的 JSON\n{response.text}")
    return False, 0.0


def analyze_result(data: Dict[str, Any]) -> tuple[bool, float]:
    """解析并打印 API 返回结果"""
    code = data.get("code")
    message = data.get("message", "未知消息")
    if code == 0:
        points = data.get("points", 0)
        balance = float(data["list"][0]["balance"])
        print(f"✅ 签到成功！{message} (获得 {points} 积分，余额 {balance:.0f} 积分)")
        return True, balance
    if code == 1:
        balance = float(data["list"][0]["balance"])
        print(f"ℹ️  提示: {message} (今天已经签到过了，余额 {balance:.0f} 积分)")
        return True, balance
    print(f"❌ 签到失败: {message} (Error Code: {code})")
    return False, 0.0


if __name__ == "__main__":
    import sys
    setup_cookies()
    success, balance = run_checkin()
    if success and balance >= 500:
        print("🎉 恭喜！你已经满足兑换条件，可以进行兑换了！")
        run_exchange()
    sys.exit(0 if success else 1)
