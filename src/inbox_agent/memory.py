import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, Field, field_validator

from inbox_agent.config import (
    HISTORY_MEMORY_FILE,
    INBOX_MEMORY_FILE,
    INBOX_STATE_KEY,
    IS_CI,
    get_now_bjt,
)
from utils.timezone import parse_bjt_datetime


class ScheduleItem(BaseModel):
    """结构化待办日程模型"""

    schedule_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    message_id: str = ""
    title: str
    subject: str = ""
    from_addr: str = Field(default="", alias="from")
    tldr: str = ""
    action_items: list[str] = Field(default_factory=list)
    event_date: datetime
    event_time: str = ""
    start_time: str = ""
    end_time: str = ""
    timezone: str = "Asia/Shanghai"  # 酒店、航班等跨时区行程明确时区（如 Asia/Tokyo, America/New_York）
    advance_days: int = 3
    priority: str = "P1"
    added_at: datetime = Field(default_factory=get_now_bjt)
    updated_at: datetime | None = None

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    @field_validator("event_date", mode="before")
    @classmethod
    def _coerce_event_date(cls, v: Any) -> datetime:
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError("event_date 不能为空，日程必须绑定具体日期")
        return parse_bjt_datetime(v).start_of("day")

    @field_validator("added_at", "updated_at", mode="before")
    @classmethod
    def _coerce_optional_dt(cls, v: Any) -> datetime | None:
        if v is None or v == "":
            return None
        return parse_bjt_datetime(v)

    @property
    def event_date_str(self) -> str:
        dt = parse_bjt_datetime(self.event_date)
        return dt.format("YYYY-MM-DD")


class InboxStateData(BaseModel):
    """日常收件箱记忆状态 (Schema v2, Datetime 强类型)"""

    version: int = 2
    processed_message_ids: list[str] = Field(default_factory=list)
    spam_message_ids: list[str] = Field(default_factory=list)
    active_schedules: list[ScheduleItem] = Field(default_factory=list)
    total_processed: int = 0
    total_spam_filtered: int = 0
    last_run: datetime | None = None

    model_config = ConfigDict(extra="ignore")

    @field_validator("last_run", mode="before")
    @classmethod
    def _coerce_last_run(cls, v: Any) -> datetime | None:
        if not v:
            return None
        return parse_bjt_datetime(v)


class HistoryStateData(BaseModel):
    """历史积压清理记忆状态 (Schema v2, Datetime 强类型)"""

    version: int = 2
    history_processed_ids: list[str] = Field(default_factory=list)
    total_pruned_90d: int = 0
    last_run: datetime | None = None

    model_config = ConfigDict(extra="ignore")

    @field_validator("last_run", mode="before")
    @classmethod
    def _coerce_last_run(cls, v: Any) -> datetime | None:
        if not v:
            return None
        return parse_bjt_datetime(v)


class EncryptedStore:
    """提供通用的 Fernet AES-128 对称加密持久化底座"""

    def __init__(self, filepath: Path, key: str | None = None):
        self.filepath = filepath
        self.key = key or INBOX_STATE_KEY
        self.fernet: Fernet | None = None
        if self.key:
            try:
                self.fernet = Fernet(self.key.encode())
            except Exception as e:
                print(f"[Memory Security Error] 非法的加密密钥格式: {e}", file=sys.stderr)
                if IS_CI:
                    sys.exit(1)
        else:
            if IS_CI:
                print("[Fatal Security Error] CI 环境中必须配置 INBOX_STATE_KEY Secrets！严禁明文运行！", file=sys.stderr)
                sys.exit(1)
            else:
                print("[Security Warning] 未检测到 INBOX_STATE_KEY，状态将无法加密持久化", file=sys.stderr)

    def load[T: BaseModel](self, model_cls: type[T]) -> T:
        """从磁盘解密加载 Pydantic 状态数据，支持旧版 Schema 平滑升级与脏数据容错"""
        if not self.filepath.exists():
            return model_cls()

        if not self.fernet:
            print(f"[Memory Warning] 缺少解密密钥，无法读取加密状态文件: {self.filepath}", file=sys.stderr)
            if IS_CI:
                sys.exit(1)
            return model_cls()

        try:
            encrypted_bytes = self.filepath.read_bytes()
            if not encrypted_bytes:
                return model_cls()
            decrypted_bytes = self.fernet.decrypt(encrypted_bytes)
            json_str = decrypted_bytes.decode("utf-8")
            raw_dict = json.loads(json_str)
        except InvalidToken:
            print(f"[Memory Security Error] 密钥不匹配或数据已被篡改: {self.filepath}，直接初始化全新状态", file=sys.stderr)
            return model_cls()
        except Exception as e:
            print(f"[Memory Warning] 读取或解密状态文件异常 ({e})，按照破坏性升级规则重置为全新状态", file=sys.stderr)
            return model_cls()

        # 显式版本迁移与平滑升级管道
        if isinstance(raw_dict, dict):
            raw_dict = self._migrate_to_latest(raw_dict)

        # 待办日程条目级容错隔离 (防止单条损坏条目清空整库)
        valid_schedules: list[ScheduleItem] = []
        if isinstance(raw_dict, dict) and "active_schedules" in raw_dict and isinstance(raw_dict["active_schedules"], list):
            for s_raw in raw_dict["active_schedules"]:
                if not isinstance(s_raw, dict):
                    continue
                try:
                    valid_schedules.append(ScheduleItem.model_validate(s_raw))
                except Exception as ex:
                    print(f"[Memory Warning] 跳过格式损坏的历史日程条目 ({ex})", file=sys.stderr)
            raw_dict["active_schedules"] = [s.model_dump(mode="json") for s in valid_schedules]

        try:
            return model_cls.model_validate(raw_dict)
        except Exception as e:
            print(f"[Memory Warning] 状态数据顶层校验异常 ({e})，启动最大化数据挽救兜底降级", file=sys.stderr)
            fallback_instance = model_cls()
            if isinstance(raw_dict, dict):
                # 尽全力保留历史已处理 message_id 列表，绝不重复处理
                if hasattr(fallback_instance, "processed_message_ids") and "processed_message_ids" in raw_dict:
                    fallback_instance.processed_message_ids = [str(x) for x in raw_dict.get("processed_message_ids", []) if x]
                if hasattr(fallback_instance, "history_processed_ids") and "history_processed_ids" in raw_dict:
                    fallback_instance.history_processed_ids = [str(x) for x in raw_dict.get("history_processed_ids", []) if x]
                # 挽救已通过校验的有效日程池与统计计数，绝不丢失
                if hasattr(fallback_instance, "active_schedules") and valid_schedules:
                    fallback_instance.active_schedules = valid_schedules
                if hasattr(fallback_instance, "total_processed") and "total_processed" in raw_dict:
                    try:
                        fallback_instance.total_processed = int(raw_dict.get("total_processed", 0))
                    except Exception:
                        pass
            return fallback_instance

    @staticmethod
    def _migrate_to_latest(raw_dict: dict[str, Any]) -> dict[str, Any]:
        """状态版本显式升级管道 (Schema v1 -> v2)"""
        version = raw_dict.get("version", 1)
        if version < 2:
            print(f"[Memory Migration] 检测到旧版本状态 (Schema v{version})，启动平滑升级至 Schema v2...", file=sys.stderr)
            if "active_schedules" in raw_dict and isinstance(raw_dict["active_schedules"], list):
                cleaned_schedules = []
                now_iso = get_now_bjt().isoformat()
                for item in raw_dict["active_schedules"]:
                    if not isinstance(item, dict):
                        continue
                    ev_date = item.get("event_date")
                    if not ev_date or not str(ev_date).strip():
                        continue
                    try:
                        # 规范化旧日期格式
                        item["event_date"] = parse_bjt_datetime(ev_date).start_of("day").isoformat()
                    except Exception:
                        continue

                    # 补齐/规范化 added_at (必填时间戳，缺失补当前时间)
                    added_val = item.get("added_at")
                    if not added_val or not str(added_val).strip():
                        item["added_at"] = now_iso
                    else:
                        try:
                            item["added_at"] = parse_bjt_datetime(added_val).isoformat()
                        except Exception:
                            item["added_at"] = now_iso

                    # 规范化 updated_at (可选时间戳，缺失时保持 None 绝不误标为刚更新)
                    updated_val = item.get("updated_at")
                    if updated_val and str(updated_val).strip():
                        try:
                            item["updated_at"] = parse_bjt_datetime(updated_val).isoformat()
                        except Exception:
                            item["updated_at"] = None
                    else:
                        item["updated_at"] = None

                    # 兼容解耦旧版 event_time (若为 09:30-11:30 区间自动拆分为 start_time/end_time)
                    old_time = str(item.get("event_time") or "").strip()
                    if old_time and "-" in old_time:
                        parts = old_time.split("-", 1)
                        if not item.get("start_time"):
                            item["start_time"] = parts[0].strip()
                        if not item.get("end_time"):
                            item["end_time"] = parts[1].strip()
                    elif old_time and not item.get("start_time"):
                        item["start_time"] = old_time

                    cleaned_schedules.append(item)
                raw_dict["active_schedules"] = cleaned_schedules

            # last_run 字符串升级为规范时间戳
            if "last_run" in raw_dict and isinstance(raw_dict["last_run"], str):
                try:
                    raw_dict["last_run"] = parse_bjt_datetime(raw_dict["last_run"]).isoformat()
                except Exception:
                    raw_dict["last_run"] = get_now_bjt().isoformat()

            raw_dict["version"] = 2
        return raw_dict

    def save(self, model: BaseModel):
        """将 Pydantic 状态模型进行 Fernet 加密并持久化到磁盘"""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        if not self.fernet:
            print("[Memory Security Error] 缺少加密密钥，严禁向磁盘保存未加密的状态数据！", file=sys.stderr)
            if IS_CI:
                sys.exit(1)
            return

        try:
            json_str = model.model_dump_json(by_alias=True, indent=2)
            encrypted_bytes = self.fernet.encrypt(json_str.encode("utf-8"))
            self.filepath.write_bytes(encrypted_bytes)
        except Exception as e:
            print(f"[Memory Error] 加密保存状态文件失败 ({self.filepath}): {e}", file=sys.stderr)
            if IS_CI:
                sys.exit(1)


class InboxMemory:
    """日常邮件处理与待办日程记忆管理器 (Schema v1)"""

    def __init__(self, filepath: Path = INBOX_MEMORY_FILE, key: str | None = None):
        self.store = EncryptedStore(filepath=filepath, key=key)
        self.data: InboxStateData = self.store.load(InboxStateData)
        print(f"[InboxMemory Loaded] 状态已加载 (Schema v{self.data.version}, {len(self.data.processed_message_ids)} 封日常邮件已处理, {len(self.data.active_schedules)} 条待办日程)")

    def is_processed(self, message_id: str) -> bool:
        """主日常 CI 专用：判断该邮件是否已被日常收件箱助手处理过"""
        if not message_id:
            return False
        return message_id in self.data.processed_message_ids

    def is_confirmed_spam(self, message_id: str) -> bool:
        """检查该邮件是否已被确认为垃圾邮件 (Spam)"""
        if not message_id:
            return False
        return message_id in self.data.spam_message_ids

    def mark_processed(self, message_id: str, is_spam: bool = False):
        """记录日常邮件处理状态"""
        if not message_id:
            return

        if message_id not in self.data.processed_message_ids:
            self.data.processed_message_ids.append(message_id)
            if len(self.data.processed_message_ids) > 5000:
                self.data.processed_message_ids = self.data.processed_message_ids[-4000:]
            self.data.total_processed += 1

        if is_spam:
            if message_id not in self.data.spam_message_ids:
                self.data.spam_message_ids.append(message_id)
                if len(self.data.spam_message_ids) > 3000:
                    self.data.spam_message_ids = self.data.spam_message_ids[-2000:]
                self.data.total_spam_filtered += 1

    def add_schedule(self, schedule_item: ScheduleItem | dict) -> ScheduleItem | None:
        """将包含具体日期 (event_date) 的日程保存到待办日历池中，按 schedule_id 或 (message_id + title + event_date) 覆盖去重"""
        try:
            if isinstance(schedule_item, dict):
                title = schedule_item.get("title") or schedule_item.get("subject") or "未命名日程"
                payload = {**schedule_item, "title": title}
                item = ScheduleItem.model_validate(payload)
            else:
                item = schedule_item
        except Exception as e:
            print(f"[Memory Warning] 日程数据非法，跳过加入待办池: {e}", file=sys.stderr)
            return None

        item_ev_date = parse_bjt_datetime(item.event_date).start_of("day")

        # 依据 schedule_id 或 (message_id + title + event_date) 查重与就地覆盖更新
        for existing in self.data.active_schedules:
            existing_ev_date = parse_bjt_datetime(existing.event_date).start_of("day")
            same_date = existing_ev_date.date() == item_ev_date.date()
            match = False
            if item.schedule_id and existing.schedule_id == item.schedule_id:
                match = True
            elif (
                item.message_id
                and existing.message_id == item.message_id
                and existing.title == item.title
                and same_date
            ):
                match = True
            elif not item.message_id and existing.title == item.title and same_date:
                match = True

            if match:
                existing.title = item.title
                existing.subject = item.subject or existing.subject or item.title
                existing.from_addr = item.from_addr or existing.from_addr
                existing.tldr = item.tldr or existing.tldr
                existing.action_items = item.action_items or existing.action_items
                existing.event_date = item_ev_date
                existing.event_time = item.event_time or existing.event_time
                existing.timezone = item.timezone or existing.timezone
                existing.advance_days = item.advance_days
                existing.priority = item.priority
                existing.updated_at = get_now_bjt()
                return existing

        self.data.active_schedules.append(item)
        return item

    def get_due_schedules(self, today_str: str = "", now: datetime | None = None) -> list[dict]:
        """
        获取当前需要提醒的日程列表：
        - 今天到期 (days_left == 0)
        - 预警期内 (0 < days_left <= advance_days)
        - 已逾期 1 天 (days_left == -1)；逾期 1 天以上直接过滤不显示
        """
        if now is not None:
            now_dt = parse_bjt_datetime(now)
        elif today_str:
            now_dt = parse_bjt_datetime(today_str)
        else:
            now_dt = get_now_bjt()

        today_date = now_dt.date()
        due_list = []
        for item in self.data.active_schedules:
            ev_dt = parse_bjt_datetime(item.event_date).start_of("day")
            ev_date = ev_dt.date()
            delta_days = (ev_date - today_date).days
            advance = item.advance_days

            item_dict = item.model_dump(mode="json", by_alias=True)
            item_dict["event_date"] = ev_dt.format("YYYY-MM-DD")
            if delta_days == 0:
                item_dict["due_status"] = "今天到期"
                item_dict["days_left"] = 0
                due_list.append(item_dict)
            elif 0 < delta_days <= advance:
                item_dict["due_status"] = f"还剩 {delta_days} 天"
                item_dict["days_left"] = delta_days
                due_list.append(item_dict)
            elif delta_days == -1:
                item_dict["due_status"] = "已逾期 1 天"
                item_dict["days_left"] = -1
                due_list.append(item_dict)
            # 逾期 1 天以上 (delta_days < -1) 不再纳入提醒视图

        due_list.sort(key=lambda x: x.get("days_left", 999))
        return due_list

    def prune_expired_schedules(self, today_str: str = "", now: datetime | None = None):
        """清理已过期超过 3 天的历史日程"""
        if now is not None:
            now_dt = parse_bjt_datetime(now)
        elif today_str:
            now_dt = parse_bjt_datetime(today_str)
        else:
            now_dt = get_now_bjt()

        today_date = now_dt.date()
        retained = []
        for item in self.data.active_schedules:
            ev_date = parse_bjt_datetime(item.event_date).date()
            if (today_date - ev_date).days <= 3:
                retained.append(item)
        self.data.active_schedules = retained

    def get_active_schedules(self) -> list[dict]:
        """获取当前所有活跃待办日程 (返回 JSON-safe 字典，防止进入 json.dumps 时因 DateTime 导致 TypeError)"""
        return [
            {**item.model_dump(mode="json", by_alias=True), "event_date": item.event_date_str}
            for item in self.data.active_schedules
        ]

    def remove_schedule(self, schedule_id: str) -> bool:
        """根据唯一 schedule_id 明确移除指定日程条目，返回是否成功删除"""
        target_id = (schedule_id or "").strip()
        if not target_id:
            return False

        initial_len = len(self.data.active_schedules)
        self.data.active_schedules = [item for item in self.data.active_schedules if item.schedule_id != target_id]
        return len(self.data.active_schedules) < initial_len

    def remove_schedules_by_message_id(self, message_id: str) -> list[dict]:
        """按邮件 RFC 822 Message-ID 移除该邮件关联的日程（用于撤回或取消场景）"""
        target_msg_id = (message_id or "").strip()
        if not target_msg_id:
            return []

        retained = []
        removed = []
        for item in self.data.active_schedules:
            if item.message_id == target_msg_id:
                removed.append({**item.model_dump(mode="json", by_alias=True), "event_date": item.event_date_str})
            else:
                retained.append(item)
        self.data.active_schedules = retained
        return removed

    def save(self):
        """保存日常记忆状态"""
        self.data.last_run = get_now_bjt()
        self.store.save(self.data)
        print(f"[InboxMemory Saved] 状态已成功进行 Fernet 对称加密并保存至: {self.store.filepath}")


class HistoryMemory:
    """历史积压老邮件清理记忆管理器 (Schema v1)"""

    def __init__(self, filepath: Path = HISTORY_MEMORY_FILE, key: str | None = None):
        self.store = EncryptedStore(filepath=filepath, key=key)
        self.data: HistoryStateData = self.store.load(HistoryStateData)
        print(f"[HistoryMemory Loaded] 状态已加载 (Schema v{self.data.version}, {len(self.data.history_processed_ids)} 封历史积压已清理)")

    def is_processed(self, message_id: str) -> bool:
        """判断该历史老邮件是否已被清理研判过"""
        if not message_id:
            return False
        return message_id in self.data.history_processed_ids

    def mark_processed(self, message_id: str):
        """标记该历史老邮件已清理处理"""
        if not message_id:
            return
        if message_id not in self.data.history_processed_ids:
            self.data.history_processed_ids.append(message_id)
            if len(self.data.history_processed_ids) > 5000:
                self.data.history_processed_ids = self.data.history_processed_ids[-4000:]

    def record_pruned(self, count: int):
        """累加清理统计"""
        self.data.total_pruned_90d += count

    @property
    def pruned_count(self) -> int:
        """获取累计清理的90天老邮件总数"""
        return self.data.total_pruned_90d

    @property
    def total_pruned(self) -> int:
        """获取累计清理的90天老邮件总数"""
        return self.data.total_pruned_90d

    def save(self):
        """保存历史清理记忆状态"""
        self.data.last_run = get_now_bjt()
        self.store.save(self.data)
        print(f"[HistoryMemory Saved] 历史清理状态已成功进行 Fernet 对称加密并保存至: {self.store.filepath}")
