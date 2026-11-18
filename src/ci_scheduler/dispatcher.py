"""仅负责发起工作流，不执行报告或读取报告密钥。"""

from urllib.parse import quote

import requests


class DispatchError(Exception):
    def __init__(self, message: str, *, uncertain: bool):
        super().__init__(message)
        self.uncertain = uncertain


def dispatch(repository: str, workflow: str, ref: str, token: str) -> str:
    """单次 POST；不重试可能已经成功的请求。"""
    url = f"https://api.github.com/repos/{repository}/actions/workflows/{quote(workflow, safe='')}/dispatches"
    try:
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2026-03-10",
            },
            json={"ref": ref},
            timeout=(10, 30),
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        # 不输出请求对象、headers 或异常全文，避免凭据进入日志。
        raise DispatchError(f"网络异常（{type(exc).__name__}），结果未知，请先检查 Actions", uncertain=True) from exc
    with response:
        if response.status_code not in {200, 204}:
            raise DispatchError(f"GitHub API 返回 HTTP {response.status_code}", uncertain=response.status_code >= 500)
        fallback = f"https://github.com/{repository}/actions/workflows/{quote(workflow, safe='')}"
        if response.status_code == 204:
            return fallback
        try:
            body = response.json()
        except ValueError:
            return fallback  # 请求已成功，缺少运行链接也不得重发。
        return (body.get("html_url") or fallback) if isinstance(body, dict) else fallback
