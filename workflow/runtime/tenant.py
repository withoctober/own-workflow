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

    @property
    def api_mode(self) -> str:
        return str(self.payload.get("api_mode") or "system").strip().lower() or "system"

    @property
    def api_ref(self) -> dict[str, Any]:
        value = self.payload.get("api_ref")
        return value if isinstance(value, dict) else {}

    @property
    def default_llm_model(self) -> str:
        return str(self.payload.get("default_llm_model") or "").strip()
