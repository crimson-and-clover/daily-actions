"""将 PR 评论中的 CI 命令转发给已注册的工作流。"""

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


@dataclass(frozen=True)
class Command:
    name: str
    workflow: str
    same_repo_only: bool = False


COMMANDS = {
    "/ai-review": Command("Qodo", "ai-review.yml"),
    "/ai-deep-review": Command("OpenHands", "ai-deep-review.yml", same_repo_only=True),
}


def parse_commands(body: str) -> list[str]:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if any(line not in COMMANDS for line in lines):
        return []
    return list(dict.fromkeys(lines))


def github_api(endpoint: str, payload: dict | None = None) -> dict:
    args = ["gh", "api", "-H", "X-GitHub-Api-Version: 2026-03-10", endpoint]
    if payload is not None:
        args.extend(["--method", "POST", "--input", "-"])
    result = subprocess.run(
        args,
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True,
        encoding="utf-8",
        check=True,
        timeout=30,
    )
    return json.loads(result.stdout) if result.stdout.strip() else {}


def post_receipt(endpoint: str, body: str) -> None:
    try:
        github_api(endpoint, {"body": body})
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise RuntimeError("发送 CI 回执失败，请根据入口日志确认派发结果。") from exc


def launch_workflows(event: dict) -> int:
    issue = event.get("issue", {})
    comment = event.get("comment", {})
    author = comment.get("user") or {}
    if event.get("action") != "created" or not issue.get("pull_request") or author.get("type") != "User":
        return 0
    commands = parse_commands(comment.get("body") or "")
    if not commands:
        return 0

    repository = os.environ["GITHUB_REPOSITORY"]
    repo_path = f"repos/{repository}"
    login = quote(author["login"], safe="")
    access = github_api(f"{repo_path}/collaborators/{login}/permission")
    if access.get("permission") not in {"write", "maintain", "admin"}:
        return 0

    number = issue["number"]
    pr = github_api(f"{repo_path}/pulls/{number}")
    reply_endpoint = f"{repo_path}/issues/{number}/comments"
    source = comment["html_url"]
    if pr["state"] != "open":
        post_receipt(reply_endpoint, f"[CI 请求]({source})未执行，PR #{number} 已关闭。")
        return 0

    head_sha = pr["head"]["sha"]
    head_repo = (pr["head"].get("repo") or {}).get("full_name", "")
    payload = {
        "ref": event["repository"]["default_branch"],
        "inputs": {"pr_number": str(number), "head_sha": head_sha},
    }
    lines = [f"[CI 请求]({source}) · PR #{number} · `{head_sha[:7]}`", ""]
    had_error = False
    for command in commands:
        spec = COMMANDS[command]
        name, workflow = spec.name, spec.workflow
        if spec.same_repo_only and head_repo.casefold() != repository.casefold():
            lines.append(f"- {name}：未发起，只支持同仓库分支。")
            continue
        try:
            run = github_api(f"{repo_path}/actions/workflows/{workflow}/dispatches", payload)
        except subprocess.CalledProcessError as exc:
            print(f"{workflow} dispatch failed: {exc.stderr.strip()!r}")
            lines.append(f"- {name}：发起失败，详见入口 CI 日志。")
            had_error = True
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            print(f"{workflow} dispatch outcome unknown: {str(exc)!r}")
            lines.append(f"- {name}：未能确认是否发起，请先查看 Actions。")
            had_error = True
        else:
            server = os.environ["GITHUB_SERVER_URL"]
            run_url = run.get("html_url") or f"{server}/{repository}/actions/workflows/{workflow}"
            print(f"{name} 已提交运行：{run_url}", flush=True)
            lines.append(f"- {name}：已提交运行 · [查看 CI]({run_url})")

    if had_error:
        router_url = f"{os.environ['GITHUB_SERVER_URL']}/{repository}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
        lines.extend(["", f"[查看入口 CI]({router_url})"])
    post_receipt(reply_endpoint, "\n".join(lines))
    return int(had_error)


if __name__ == "__main__":
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    raise SystemExit(launch_workflows(event))
