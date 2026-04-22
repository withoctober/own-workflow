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

    @classmethod
    def from_root(cls, root: Path) -> "WorkflowSettings":
        return cls(
            root=root,
            config_dir=root / "config",
            run_dir=root / "var" / "runs",
            database_url=env_value("DATABASE_URL", root) or "",
            schedule_poll_interval_seconds=float(env_value("SCHEDULE_POLL_INTERVAL_SECONDS", root) or 15),
            schedule_stale_lock_seconds=int(env_value("SCHEDULE_STALE_LOCK_SECONDS", root) or 600),
        )
