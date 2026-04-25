from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re
import threading
import time
from typing import Iterable
from zoneinfo import ZoneInfo

from model import (
    TenantFlowSchedule,
    claim_tenant_flow_schedule,
    complete_tenant_flow_schedule_run,
    ensure_postgres_tables,
    get_tenant_runtime_config,
    list_active_schedules_without_next_run,
    list_due_tenant_flow_schedules,
    postgres_enabled,
    reset_stale_tenant_flow_schedule_locks,
    update_tenant_flow_schedule_next_run,
)
from workflow.flow.registry import has_flow_definition
from workflow.runtime.engine import GraphRuntime, RunRequest
from workflow.runtime.tenant import TenantRuntimeConfig
from workflow.settings import WorkflowSettings


SCHEDULE_TIMEZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class CronField:
    values: frozenset[int]
    is_wildcard: bool


@dataclass(frozen=True, slots=True)
class CronSchedule:
    minute: CronField
    hour: CronField
    day_of_month: CronField
    month: CronField
    day_of_week: CronField

    def matches(self, when: datetime) -> bool:
        weekday = (when.weekday() + 1) % 7
        if when.minute not in self.minute.values:
            return False
        if when.hour not in self.hour.values:
            return False
        if when.month not in self.month.values:
            return False
        day_matches = when.day in self.day_of_month.values
        weekday_matches = weekday in self.day_of_week.values
        if self.day_of_month.is_wildcard and self.day_of_week.is_wildcard:
            return True
        if self.day_of_month.is_wildcard:
            return weekday_matches
        if self.day_of_week.is_wildcard:
            return day_matches
        return day_matches or weekday_matches


def _parse_field(field: str, *, minimum: int, maximum: int, allow_sunday_7: bool = False) -> CronField:
    value_set: set[int] = set()
    is_wildcard = field == "*"
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise ValueError("cron 字段不能为空")
        if part == "*":
            value_set.update(range(minimum, maximum + 1))
            continue
        if "/" in part:
            base, step_text = part.split("/", 1)
            if not step_text.isdigit():
                raise ValueError(f"无效的 cron 步长: {part}")
            step = int(step_text)
            if step <= 0:
                raise ValueError(f"cron 步长必须大于 0: {part}")
        else:
            base = part
            step = 1
        if base == "*":
            start = minimum
            end = maximum
        elif "-" in base:
            start_text, end_text = base.split("-", 1)
            if not start_text.isdigit() or not end_text.isdigit():
                raise ValueError(f"无效的 cron 范围: {part}")
            start = int(start_text)
            end = int(end_text)
        else:
            if not base.isdigit():
                raise ValueError(f"无效的 cron 值: {part}")
            start = int(base)
            end = int(base)
        if allow_sunday_7 and start == 7:
            start = 0
        if allow_sunday_7 and end == 7:
            end = 0
        if start < minimum or start > maximum:
            raise ValueError(f"cron 值超出范围: {part}")
        if end < minimum or end > maximum:
            raise ValueError(f"cron 值超出范围: {part}")
        if base != "*" and "-" in base and start > end:
            raise ValueError(f"cron 范围起始值不能大于结束值: {part}")
        if allow_sunday_7 and base == "7":
            value_set.add(0)
            continue
        if allow_sunday_7 and "-" in base and 0 in {start, end} and "7" in base:
            raise ValueError(f"weekday 范围不能跨越 7/0 边界: {part}")
        value_set.update(range(start, end + 1, step))
    if not value_set:
        raise ValueError("cron 字段解析后为空")
    return CronField(values=frozenset(sorted(value_set)), is_wildcard=is_wildcard)


def parse_cron_expression(expr: str) -> CronSchedule:
    parts = [part.strip() for part in expr.strip().split()]
    if len(parts) != 5:
        raise ValueError("cron 表达式必须是 5 段: 分 时 日 月 周")
    minute, hour, day_of_month, month, day_of_week = parts
    return CronSchedule(
        minute=_parse_field(minute, minimum=0, maximum=59),
        hour=_parse_field(hour, minimum=0, maximum=23),
        day_of_month=_parse_field(day_of_month, minimum=1, maximum=31),
        month=_parse_field(month, minimum=1, maximum=12),
        day_of_week=_parse_field(day_of_week, minimum=0, maximum=6, allow_sunday_7=True),
    )


def validate_cron_expression(expr: str) -> None:
    parse_cron_expression(expr)


def now_in_schedule_timezone() -> datetime:
    return datetime.now(SCHEDULE_TIMEZONE)


def compute_next_run_at(expr: str, *, after: datetime | None = None) -> datetime:
    schedule = parse_cron_expression(expr)
    current = (after or now_in_schedule_timezone()).astimezone(SCHEDULE_TIMEZONE)
    candidate = current.replace(second=0, microsecond=0) + timedelta(minutes=1)
    max_checks = 60 * 24 * 366 * 2
    for _ in range(max_checks):
        if schedule.matches(candidate):
            return candidate
        candidate += timedelta(minutes=1)
    raise ValueError(f"无法在合理时间内计算下次触发时间: {expr}")


def normalize_batch_id_prefix(raw: str) -> str:
    cleaned = re.sub(r"[^a-z0-9-]+", "-", raw.strip().lower())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned[:32]


class TenantFlowScheduler:
    def __init__(
        self,
        settings: WorkflowSettings,
        runtime: GraphRuntime,
        *,
        poll_interval_seconds: float = 15.0,
        stale_lock_seconds: int = 600,
    ) -> None:
        self.settings = settings
        self.runtime = runtime
        self.poll_interval_seconds = poll_interval_seconds
        self.stale_lock_seconds = stale_lock_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not postgres_enabled(self.settings.database_url):
            return
        ensure_postgres_tables(self.settings.database_url)
        self.recover()
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="tenant-flow-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(self.poll_interval_seconds, 1.0) + 1.0)
            self._thread = None

    def recover(self) -> None:
        if not postgres_enabled(self.settings.database_url):
            return
        stale_before = now_in_schedule_timezone() - timedelta(seconds=self.stale_lock_seconds)
        reset_stale_tenant_flow_schedule_locks(self.settings.database_url, stale_before=stale_before)
        for schedule in list_active_schedules_without_next_run(self.settings.database_url):
            next_run_at = compute_next_run_at(schedule.cron_expr)
            update_tenant_flow_schedule_next_run(
                self.settings.database_url,
                schedule_id=schedule.id,
                next_run_at=next_run_at,
            )

    def run_pending(self) -> int:
        if not postgres_enabled(self.settings.database_url):
            return 0
        due_at = now_in_schedule_timezone()
        processed = 0
        for schedule in list_due_tenant_flow_schedules(self.settings.database_url, run_at=due_at):
            claimed = claim_tenant_flow_schedule(self.settings.database_url, schedule_id=schedule.id, run_at=due_at)
            if claimed is None:
                continue
            self._execute_schedule(claimed)
            processed += 1
        return processed

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_pending()
            except Exception:
                # Keep the scheduler alive; execution errors are written back per schedule.
                pass
            self._stop_event.wait(self.poll_interval_seconds)

    def _execute_schedule(self, schedule: TenantFlowSchedule) -> None:
        finished_at = now_in_schedule_timezone()
        next_run_at: datetime | None = compute_next_run_at(schedule.cron_expr, after=finished_at) if schedule.is_active else None
        batch_id = build_schedule_batch_id(schedule, finished_at)
        last_status = "failed"
        last_error = ""
        try:
            if not has_flow_definition(schedule.flow_id):
                raise RuntimeError(f"unknown flow: {schedule.flow_id}")
            runtime_payload = get_tenant_runtime_config(self.settings.database_url, schedule.tenant_id)
            if runtime_payload is None:
                raise RuntimeError(f"PostgreSQL 中未找到 tenant_id={schedule.tenant_id} 的运行配置")
            request_payload = schedule.request_payload if isinstance(schedule.request_payload, dict) else {}
            result = self.runtime.run(
                RunRequest(
                    flow_id=schedule.flow_id,
                    tenant_id=schedule.tenant_id,
                    batch_id=batch_id,
                    trigger_mode="cron",
                    source_url=str(request_payload.get("source_url") or ""),
                    tenant_runtime_config=TenantRuntimeConfig(payload=runtime_payload),
                )
            )
            last_status = str(result.get("status") or "completed")
            errors = list(result.get("errors", [])) if isinstance(result.get("errors"), list) else []
            last_error = "; ".join(str(item) for item in errors if str(item).strip())
        except Exception as exc:
            last_status = "failed"
            last_error = str(exc)
        finally:
            complete_tenant_flow_schedule_run(
                self.settings.database_url,
                schedule_id=schedule.id,
                next_run_at=next_run_at,
                last_run_at=finished_at,
                last_status=last_status,
                last_error=last_error,
                last_batch_id=batch_id,
            )


def build_schedule_batch_id(schedule: TenantFlowSchedule, now: datetime | None = None) -> str:
    current = (now or now_in_schedule_timezone()).astimezone(SCHEDULE_TIMEZONE)
    prefix = normalize_batch_id_prefix(schedule.batch_id_prefix)
    timestamp = current.strftime("%Y%m%d%H%M%S")
    if prefix:
        return f"{prefix}-{timestamp}"
    return f"cron-{timestamp}"
