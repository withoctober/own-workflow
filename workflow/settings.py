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

    @classmethod
    def from_root(cls, root: Path) -> "WorkflowSettings":
        return cls(
            root=root,
            config_dir=root / "config",
            run_dir=root / "var" / "runs",
            database_url=env_value("DATABASE_URL", root) or "",
        )
