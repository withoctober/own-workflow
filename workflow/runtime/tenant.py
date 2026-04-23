from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TenantRuntimeConfig:
    payload: dict[str, Any]

    @property
    def tenant_id(self) -> str:
        return str(self.payload.get("tenant_id") or "").strip()

    @property
    def database_url(self) -> str:
        return str(self.payload.get("database_url") or "").strip()

    @property
    def store_type(self) -> str:
        return str(self.payload.get("store_type") or "").strip().lower() or "database"
