from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from workflow.core.env import env_value


@dataclass
class WorkflowSettings:
    root: Path
    config_dir: Path
    run_dir: Path
    database_url: str
    schedule_poll_interval_seconds: float
    schedule_stale_lock_seconds: int
    tikhub_recharge_url: str
    tikhub_console_url: str
    tikhub_log_url: str
    llm_recharge_url: str
    llm_console_url: str
    llm_log_url: str

    @classmethod
    def from_root(cls, root: Path) -> "WorkflowSettings":
        return cls(
            root=root,
            config_dir=root / "config",
            run_dir=root / "var" / "runs",
            database_url=env_value("DATABASE_URL", root) or "",
            schedule_poll_interval_seconds=float(env_value("SCHEDULE_POLL_INTERVAL_SECONDS", root) or 15),
            schedule_stale_lock_seconds=int(env_value("SCHEDULE_STALE_LOCK_SECONDS", root) or 600),
            tikhub_recharge_url=env_value("TIKHUB_RECHARGE_URL", root) or "https://user.tikhub.io/dashboard/add-credit",
            tikhub_console_url=env_value("TIKHUB_CONSOLE_URL", root) or "https://user.tikhub.io/dashboard/overview",
            tikhub_log_url=env_value("TIKHUB_LOG_URL", root) or "https://user.tikhub.io/dashboard/log",
            llm_recharge_url=env_value("LLM_RECHARGE_URL", root) or "https://right.codes/subscribe",
            llm_console_url=env_value("LLM_CONSOLE_URL", root) or "https://right.codes/api-keys",
            llm_log_url=env_value("LLM_LOG_URL", root) or "https://right.codes/use-logs",
        )
