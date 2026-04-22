from __future__ import annotations

import copy
import pickle
from collections import defaultdict
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import threading
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from workflow.runtime.context import RuntimeContext
from workflow.jsonfile import read_json, write_json


class FileCheckpointSaver(InMemorySaver):
    """Persist LangGraph checkpoints to the run directory."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self._lock = threading.Lock()
        self._load()

    def _dump_payload(self) -> dict[str, Any]:
        return {
            "storage": {
                thread_id: {checkpoint_ns: dict(checkpoints) for checkpoint_ns, checkpoints in namespaces.items()}
                for thread_id, namespaces in self.storage.items()
            },
            "writes": dict(self.writes),
            "blobs": dict(self.blobs),
        }

    def _restore_storage(self, payload: dict[str, Any]) -> None:
        self.storage = defaultdict(lambda: defaultdict(dict))
        for thread_id, namespaces in payload.get("storage", {}).items():
            restored_namespaces = defaultdict(dict)
            for checkpoint_ns, checkpoints in dict(namespaces).items():
                restored_namespaces[str(checkpoint_ns)] = dict(checkpoints)
            self.storage[str(thread_id)] = restored_namespaces
        self.writes = defaultdict(dict, dict(payload.get("writes", {})))
        self.blobs = dict(payload.get("blobs", {}))

    def _flush(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_name(f"{self.path.name}.{threading.get_ident()}.tmp")
            temp_path.write_bytes(pickle.dumps(self._dump_payload()))
            temp_path.replace(self.path)

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = pickle.loads(self.path.read_bytes())
        except (OSError, EOFError, pickle.PickleError, ValueError):
            return
        if isinstance(payload, dict):
            self._restore_storage(payload)

    def put(
        self,
        config: RunnableConfig,
        checkpoint,
        metadata,
        new_versions,
    ) -> RunnableConfig:
        next_config = super().put(config, checkpoint, metadata, new_versions)
        self._flush()
        return next_config

    def put_writes(
        self,
        config: RunnableConfig,
        writes,
        task_id: str,
        task_path: str = "",
    ) -> None:
        super().put_writes(config, writes, task_id, task_path)
        self._flush()

    def delete_thread(self, thread_id: str) -> None:
        super().delete_thread(thread_id)
        self._flush()


@dataclass
class StateRepository:
    context: RuntimeContext

    def _timestamp(self) -> str:
        return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")

    @property
    def checkpointer(self) -> FileCheckpointSaver:
        return FileCheckpointSaver(self.context.checkpoint_file)

    @property
    def config(self) -> RunnableConfig:
        return {"configurable": {"thread_id": self.context.thread_id}}

    def load(self) -> dict:
        if self.context.state_file.exists():
            try:
                return read_json(self.context.state_file)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                return self.context.base_state()
        return self.context.base_state()

    def save(self, state: dict) -> None:
        state["updated_at"] = self._timestamp()
        write_json(self.context.state_file, state)

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        state = self.load()
        merged = self.merge_state(state, patch)
        self.save(merged)
        return merged

    def append_event(self, event: dict[str, Any]) -> None:
        payload = dict(event)
        payload.setdefault("timestamp", self._timestamp())
        self.context.events_file.parent.mkdir(parents=True, exist_ok=True)
        with self.context.events_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def mark_run_started(self) -> dict[str, Any]:
        initial_state = self.load()
        initial_state["status"] = "running"
        initial_state["updated_at"] = self._timestamp()
        write_json(self.context.state_file, initial_state)
        self.append_event(
            {
                "type": "run_started",
                "flow_id": self.context.flow_id,
                "tenant_id": self.context.tenant_id,
                "batch_id": self.context.batch_id,
            }
        )
        return initial_state

    def prepare_resume(self) -> dict[str, Any]:
        state = self.load()
        current_status = str(state.get("status", "")).strip().lower()
        if current_status not in {"failed", "blocked"}:
            raise ValueError(f"run status '{current_status or 'unknown'}' does not support resume")

        resume_node = self._resolve_resume_node(state)
        statuses = copy.deepcopy(dict(state.get("node_statuses", {})))
        if resume_node:
            statuses.pop(resume_node, None)

        state["status"] = "running"
        state["current_node"] = ""
        state["errors"] = []
        state["node_statuses"] = statuses
        state["resume_count"] = int(state.get("resume_count", 0)) + 1
        state["resumed_from_node"] = resume_node
        state["last_resumed_at"] = self._timestamp()
        self.reset_checkpoint()
        self.save(state)
        self.append_event(
            {
                "type": "run_resumed",
                "flow_id": self.context.flow_id,
                "tenant_id": self.context.tenant_id,
                "batch_id": self.context.batch_id,
                "resume_node": resume_node,
                "resume_count": state["resume_count"],
            }
        )
        return state

    def reset_checkpoint(self) -> None:
        self.checkpointer.delete_thread(self.context.thread_id)

    def should_skip_node(self, node_id: str) -> bool:
        state = self.load()
        if str(state.get("status", "")).strip().lower() != "running":
            return False
        completed_nodes = {str(item) for item in state.get("completed_nodes", [])}
        return node_id in completed_nodes and int(state.get("resume_count", 0)) > 0

    def mark_node_skipped(self, node_id: str) -> dict[str, Any]:
        state = self.load()
        self.append_event(
            {
                "type": "node_skipped",
                "node_id": node_id,
                "reason": "resume_completed_node",
            }
        )
        statuses = copy.deepcopy(dict(state.get("node_statuses", {})))
        node_state = copy.deepcopy(dict(statuses.get(node_id, {})))
        node_state["status"] = "completed"
        node_state["updated_at"] = self._timestamp()
        node_state.setdefault("message", "resume skipped completed node")
        statuses[node_id] = node_state
        state["node_statuses"] = statuses
        state["current_node"] = ""
        self.save(state)
        return state

    def mark_node_started(self, node_id: str) -> dict[str, Any]:
        state = self.load()
        statuses = copy.deepcopy(dict(state.get("node_statuses", {})))
        statuses[node_id] = {
            "status": "running",
            "started_at": self._timestamp(),
            "updated_at": self._timestamp(),
        }
        state["status"] = "running"
        state["current_node"] = node_id
        state["node_statuses"] = statuses
        self.save(state)
        self.append_event({"type": "node_started", "node_id": node_id})
        return state

    def mark_node_finished(self, node_id: str, result_patch: dict[str, Any], duration_ms: int) -> dict[str, Any]:
        state = self.update(result_patch)
        statuses = copy.deepcopy(dict(state.get("node_statuses", {})))
        node_state = copy.deepcopy(dict(statuses.get(node_id, {})))
        patch_status = str(result_patch.get("status", "")).strip().lower()
        if patch_status == "soft_failed":
            node_state["status"] = "soft_failed"
        else:
            node_state["status"] = "blocked" if state.get("errors") else "completed"
        node_state["updated_at"] = self._timestamp()
        node_state["duration_ms"] = duration_ms
        if result_patch.get("messages"):
            node_state["message"] = str(result_patch["messages"][-1])
        if result_patch.get("artifacts"):
            node_state["artifacts"] = result_patch["artifacts"].get(node_id, [])
        statuses[node_id] = node_state
        completed_nodes = list(state.get("completed_nodes", []))
        if node_state["status"] == "completed" and node_id not in completed_nodes:
            completed_nodes.append(node_id)
        state["completed_nodes"] = completed_nodes
        state["current_node"] = ""
        state["node_statuses"] = statuses
        if node_state["status"] == "soft_failed":
            state["status"] = "running"
        else:
            state["status"] = "blocked" if state.get("errors") else "running"
        self.save(state)
        self.append_event(
            {
                "type": "node_finished",
                "node_id": node_id,
                "status": node_state["status"],
                "duration_ms": duration_ms,
            }
        )
        return state

    def mark_node_failed(self, node_id: str, error: str, duration_ms: int) -> dict[str, Any]:
        state = self.load()
        errors = list(state.get("errors", []))
        errors.append(error)
        statuses = copy.deepcopy(dict(state.get("node_statuses", {})))
        node_state = copy.deepcopy(dict(statuses.get(node_id, {})))
        node_state["status"] = "failed"
        node_state["updated_at"] = self._timestamp()
        node_state["duration_ms"] = duration_ms
        node_state["error"] = error
        statuses[node_id] = node_state
        state["errors"] = errors
        state["current_node"] = ""
        state["status"] = "failed"
        state["node_statuses"] = statuses
        self.save(state)
        self.append_event(
            {
                "type": "node_failed",
                "node_id": node_id,
                "status": "failed",
                "duration_ms": duration_ms,
                "error": error,
            }
        )
        return state

    def mark_run_finished(self, state: dict[str, Any]) -> dict[str, Any]:
        existing_state = self.load()
        final_state = self.merge_state(existing_state, state)
        final_state["current_node"] = ""
        final_state["status"] = "completed" if not final_state.get("errors") else str(final_state.get("status", "blocked"))
        self.save(final_state)
        self.append_event(
            {
                "type": "run_finished",
                "status": final_state["status"],
                "error_count": len(final_state.get("errors", [])),
                "completed_node_count": len(final_state.get("completed_nodes", [])),
            }
        )
        return final_state

    @staticmethod
    def merge_state(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        merged = copy.deepcopy(left)
        for key, value in right.items():
            if key in {"outputs"} and isinstance(value, dict):
                current = dict(merged.get(key, {}))
                current.update(value)
                merged[key] = current
            elif key in {"artifacts"} and isinstance(value, dict):
                current = dict(merged.get(key, {}))
                current.update(value)
                merged[key] = current
            elif key in {"messages", "errors"} and isinstance(value, list):
                current = list(merged.get(key, []))
                current.extend(value)
                merged[key] = current
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _resolve_resume_node(state: dict[str, Any]) -> str:
        statuses = dict(state.get("node_statuses", {}))
        for node_id, node_state in statuses.items():
            status = str(dict(node_state).get("status", "")).strip().lower()
            if status in {"failed", "blocked", "running"}:
                return str(node_id)
        current_node = str(state.get("current_node", "")).strip()
        if current_node:
            return current_node
        return ""
