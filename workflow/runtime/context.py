from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from zoneinfo import ZoneInfo

from workflow.store.factory import build_store
from workflow.runtime.tenant import TenantRuntimeConfig
from workflow.settings import WorkflowSettings


@dataclass
class RuntimeContext:
    settings: WorkflowSettings
    flow_id: str
    batch_id: str
    tenant_id: str
    trigger_mode: str = ""
    source_url: str = ""
    tenant_runtime_config: TenantRuntimeConfig | None = None

    @property
    def root(self) -> Path:
        return self.settings.root

    @property
    def run_root(self) -> Path:
        return self.settings.run_dir / self.tenant_id / self.flow_id / self.batch_id

    @property
    def thread_id(self) -> str:
        return f"{self.tenant_id}:{self.flow_id}:{self.batch_id}"

    @property
    def state_file(self) -> Path:
        return self.run_root / "state.json"

    @property
    def checkpoint_file(self) -> Path:
        return self.run_root / "checkpoints.pkl"

    @property
    def events_file(self) -> Path:
        return self.run_root / "events.jsonl"

    @property
    def artifacts_dir(self) -> Path:
        return self.run_root / "artifacts"

    def store(self):
        return build_store(
            self.root,
            tenant_config=self.tenant_runtime_config,
        )

    def append_event(self, event: dict[str, Any]) -> None:
        from workflow.runtime.persistence import StateRepository

        StateRepository(self).append_event(event)

    def current_node_id(self) -> str:
        from workflow.runtime.persistence import StateRepository

        state = StateRepository(self).load()
        return str(state.get("current_node", "")).strip()

    def log_node_event(
        self,
        *,
        step_id: str,
        event: str,
        message: str,
        detail: dict[str, Any] | None = None,
        level: str = "info",
        duration_ms: int | None = None,
        node_id: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "type": "node_step",
            "event": event,
            "level": level,
            "node_id": node_id or self.current_node_id() or step_id,
            "step_id": step_id,
            "message": message,
        }
        if detail:
            payload["detail"] = detail
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        self.append_event(payload)

    def flow_node_ids(self) -> list[str]:
        from workflow.flow.registry import get_flow_node_ids

        return get_flow_node_ids(self.flow_id)

    def total_node_count(self) -> int:
        return len(self.flow_node_ids())

    def node_index(self, node_id: str) -> int:
        normalized = str(node_id).strip()
        if not normalized:
            return 0
        try:
            return self.flow_node_ids().index(normalized) + 1
        except ValueError:
            return 0

    def base_state(self) -> dict[str, Any]:
        now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
        return {
            "flow_id": self.flow_id,
            "tenant_id": self.tenant_id,
            "batch_id": self.batch_id,
            "trigger_mode": self.trigger_mode,
            "source_url": self.source_url,
            "status": "pending",
            "current_node": "",
            "current_node_index": 0,
            "total_node_count": self.total_node_count(),
            "completed_nodes": [],
            "node_statuses": {},
            "started_at": now,
            "updated_at": now,
            "outputs": {},
            "artifacts": {},
            "messages": [],
            "errors": [],
        }
