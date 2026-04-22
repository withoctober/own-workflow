from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TenantRuntimeConfig:
    payload: dict[str, Any]

    def feishu_resource_path(self, root: Path) -> Path:
        return (root / "config" / "_postgres_feishu_runtime.json").resolve()
