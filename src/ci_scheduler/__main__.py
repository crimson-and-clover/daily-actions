"""读取项目内 TOML 计划，常驻派发 GitHub 工作流。"""

import argparse
import logging
import os
import re
import signal
import sqlite3
import threading
import tomllib
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MAX_INSTANCES, EVENT_JOB_MISSED
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .dispatcher import DispatchError, dispatch

LOG = logging.getLogger("ci_scheduler")
BJT = ZoneInfo("Asia/Shanghai")


class BeijingFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return datetime.fromtimestamp(record.created, BJT).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Job:
    workflow: str
    cron: str
    enabled: bool = True


@dataclass(frozen=True)
class Schedule:
    repository: str
    ref: str
    timezone: ZoneInfo
    grace_seconds: int
    jobs: tuple[Job, ...]


def load_schedule(path: Path) -> Schedule:
    with path.open("rb") as source:
        data = tomllib.load(source)
    repository = data["repository"]
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        raise ValueError("repository 必须是 owner/repo")
    ref = data.get("ref", "master")
    if not isinstance(ref, str) or not ref.strip():
        raise ValueError("ref 不能为空")
    grace = data.get("grace_seconds", 300)
    if type(grace) is not int or not 0 < grace <= 3600:
        raise ValueError("grace_seconds 必须是 1 至 3600 的整数")
    jobs = []
    for item in data["jobs"]:
        workflow, expression = item["workflow"], item["cron"]
        if not re.fullmatch(r"[\w-]+\.ya?ml", workflow):
            raise ValueError(f"无效工作流文件名：{workflow}")
        if len(expression.split()) != 5:
            raise ValueError(f"{workflow} 必须使用有效的五段 cron")
        CronTrigger.from_crontab(expression, timezone=ZoneInfo(data["timezone"]))
        enabled = item.get("enabled", True)
        if type(enabled) is not bool:
            raise ValueError(f"{workflow} 的 enabled 必须是布尔值")
        jobs.append(Job(workflow, expression, enabled))
    if not jobs or len({job.workflow for job in jobs}) != len(jobs):
        raise ValueError("jobs 不能为空，且每个工作流只能配置一次")
    return Schedule(repository, ref, ZoneInfo(data["timezone"]), grace, tuple(jobs))


def open_state(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE IF NOT EXISTS dispatches (
        repository TEXT, workflow TEXT, ref TEXT, scheduled_at TEXT,
        status TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (repository, workflow, ref, scheduled_at)
    )""")
    db.commit()
    return db


def latest_due(trigger: CronTrigger, now: datetime, grace_seconds: int) -> datetime | None:
    """获取合并积压后的计划时间，作为派发记录的稳定标识，而非按实际请求时间去重。"""
    due = None
    candidate = trigger.get_next_fire_time(None, now - timedelta(seconds=grace_seconds))
    while candidate is not None and candidate <= now:
        due = candidate
        candidate = trigger.get_next_fire_time(candidate, now)
    return due.astimezone(UTC) if due is not None else None


def run_job(schedule: Schedule, job: Job, state_path: Path, token: str) -> None:
    trigger = CronTrigger.from_crontab(job.cron, timezone=schedule.timezone)
    due = latest_due(trigger, datetime.now(UTC), schedule.grace_seconds)
    if due is None:
        LOG.warning("%s 已超过补执行窗口，跳过", job.workflow)
        return
    # APScheduler 在线程池内执行任务，每次使用独立连接，不能共享主线程的 SQLite 连接。
    with closing(open_state(state_path)) as db:
        key = (schedule.repository, job.workflow, schedule.ref, due.isoformat())
        # 在发请求前提交占位；进程崩溃后保留 dispatching，不能自动重发。
        with db:
            claimed = db.execute(
                "INSERT OR IGNORE INTO dispatches (repository, workflow, ref, scheduled_at, status) VALUES (?, ?, ?, ?, 'dispatching')",
                key,
            ).rowcount
        if not claimed:
            return
        LOG.info("派发 %s，计划时间 %s", job.workflow, due.astimezone(schedule.timezone).isoformat())
        try:
            detail = dispatch(schedule.repository, job.workflow, schedule.ref, token)
        except DispatchError as exc:
            status, detail = ("unknown" if exc.uncertain else "failed"), str(exc)
            LOG.error("%s：%s；本次计划不自动重发", job.workflow, detail)
        else:
            status = "submitted"
            LOG.info("%s 已提交：%s", job.workflow, detail)
        with db:
            db.execute(
                "UPDATE dispatches SET status = ?, detail = ? WHERE repository = ? AND workflow = ? AND ref = ? AND scheduled_at = ?",
                (status, detail, *key),
            )


def create_scheduler(schedule: Schedule, state_path: Path, token: str, now: datetime) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(
        timezone=schedule.timezone,
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": schedule.grace_seconds},
    )
    for job in schedule.jobs:
        if not job.enabled:
            continue
        trigger = CronTrigger.from_crontab(job.cron, timezone=schedule.timezone)
        scheduler.add_job(
            run_job,
            trigger,
            id=job.workflow,
            args=(schedule, job, state_path, token),
            # 计划从 TOML 重建；让 APScheduler 合并宽限期内的积压，SQLite 防止重启重发。
            next_run_time=trigger.get_next_fire_time(None, now - timedelta(seconds=schedule.grace_seconds)),
        )
    scheduler.add_listener(
        lambda event: LOG.error("调度未正常执行：%s（事件代码 %s），请查看 APScheduler 日志", event.job_id, event.code),
        EVENT_JOB_ERROR | EVENT_JOB_MISSED | EVENT_JOB_MAX_INSTANCES,
    )
    return scheduler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("deploy/scheduler/schedules.toml"))
    parser.add_argument("--state", type=Path, default=Path("state/ci-scheduler/dispatches.sqlite3"))
    parser.add_argument("--check", action="store_true", help="校验计划并显示下一次时间，不请求 GitHub 或修改状态")
    args = parser.parse_args()
    handler = logging.StreamHandler()
    handler.setFormatter(BeijingFormatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    schedule = load_schedule(args.config)
    now = datetime.now(schedule.timezone)
    for job in schedule.jobs:
        if not job.enabled:
            LOG.info("%s 已暂停（enabled=false）", job.workflow)
            continue
        trigger = CronTrigger.from_crontab(job.cron, timezone=schedule.timezone)
        LOG.info("%s 下一次计划：%s", job.workflow, trigger.get_next_fire_time(None, now))
    if args.check:
        return
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise ValueError("必须设置 GITHUB_TOKEN（仅需目标仓库 Actions 写权限）")
    stopped = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopped.set())
    with closing(open_state(args.state)) as db:
        for workflow, due, status in db.execute("SELECT workflow, scheduled_at, status FROM dispatches WHERE status IN ('dispatching', 'unknown')"):
            LOG.warning("存在待人工确认的请求：%s %s %s，请检查 Actions，调度器不会重发", workflow, due, status)
    scheduler = create_scheduler(schedule, args.state, token, datetime.now(UTC))
    scheduler.start()
    try:
        stopped.wait()
    finally:
        scheduler.shutdown(wait=True)


if __name__ == "__main__":
    main()
