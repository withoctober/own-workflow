from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
import time
from typing import Any

from langgraph.graph import END, START, StateGraph

from workflow.flow.registry import build_flow_definition, list_flow_definitions
from workflow.runtime.context import RuntimeContext
from workflow.runtime.persistence import StateRepository
from workflow.runtime.tenant import TenantRuntimeConfig
from workflow.runtime.time_utils import new_batch_id
from workflow.settings import WorkflowSettings
from workflow.state import WorkflowState


@dataclass
class RunRequest:
    flow_id: str
    tenant_id: str = "default"
    batch_id: str | None = None
    trigger_mode: str = ""
    source_url: str = ""
    topic_context: dict[str, Any] | None = None
    additional_instruction: str = ""
    tenant_runtime_config: TenantRuntimeConfig | None = None
    resume: bool = False


class GraphRuntime:
    def __init__(self, settings: WorkflowSettings) -> None:
        self.settings = settings

    def list_flows(self) -> list[dict[str, Any]]:
        return list_flow_definitions()

    def build_context(self, request: RunRequest) -> RuntimeContext:
        batch_id = request.batch_id or new_batch_id()
        trigger_mode = str(request.trigger_mode or "").strip()
        if request.resume and not trigger_mode:
            state_file = self.settings.run_dir / request.tenant_id / request.flow_id / batch_id / "state.json"
            trigger_mode = self._load_existing_trigger_mode(state_file)
        return RuntimeContext(
            settings=self.settings,
            flow_id=request.flow_id,
            batch_id=batch_id,
            tenant_id=request.tenant_id,
            trigger_mode=trigger_mode,
            source_url=request.source_url,
            topic_context=request.topic_context,
            additional_instruction=request.additional_instruction,
            tenant_runtime_config=request.tenant_runtime_config,
        )

    @staticmethod
    def _load_existing_trigger_mode(state_file: Path) -> str:
        if not state_file.exists():
            return ""
        try:
            import json

            payload = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            return ""
        return str(payload.get("trigger_mode") or "").strip()

    def _execute(self, request: RunRequest, context: RuntimeContext, repository: StateRepository, state: dict[str, Any]) -> dict[str, Any]:
        flow = build_flow_definition(context)

        graph = StateGraph(WorkflowState)
        for node_name, node in flow["nodes"].items():
            graph.add_node(node_name, self._wrap_node(node_name, node, repository))
        for source, target in flow["edges"]:
            graph.add_edge(source, target)
        graph.add_edge(flow["terminal"], END)
        graph.add_edge(START, flow["entrypoint"])

        compiled = graph.compile(checkpointer=repository.checkpointer)
        try:
            final_state = compiled.invoke(state, config=repository.config)
        except Exception as exc:
            repository.mark_node_failed(str(repository.load().get("current_node", "")) or "unknown", str(exc), 0)
            raise
        return repository.mark_run_finished(final_state)

    def run(self, request: RunRequest) -> dict[str, Any]:
        context = self.build_context(request)
        repository = StateRepository(context)
        if request.resume:
            state = repository.prepare_resume()
        else:
            state = repository.mark_run_started()
        return self._execute(request, context, repository, state)

    def enqueue(self, request: RunRequest) -> dict[str, Any]:
        context = self.build_context(request)
        repository = StateRepository(context)
        if request.resume:
            initial_state = repository.prepare_resume()
        else:
            initial_state = repository.mark_run_started()

        def worker() -> None:
            try:
                self._execute(
                    RunRequest(
                        flow_id=request.flow_id,
                        tenant_id=request.tenant_id,
                        batch_id=context.batch_id,
                        trigger_mode=context.trigger_mode,
                        source_url=request.source_url,
                        topic_context=request.topic_context,
                        additional_instruction=request.additional_instruction,
                        tenant_runtime_config=request.tenant_runtime_config,
                        resume=request.resume,
                    ),
                    context,
                    repository,
                    initial_state,
                )
            except Exception:
                return

        thread = threading.Thread(
            target=worker,
            name=f"run-{context.thread_id}",
            daemon=True,
        )
        thread.start()
        return initial_state

    @staticmethod
    def _wrap_node(node_name: str, node, repository: StateRepository):
        def wrapped(state: dict[str, Any]) -> dict[str, Any]:
            if repository.should_skip_node(node_name):
                repository.mark_node_skipped(node_name)
                return {}
            repository.mark_node_started(node_name)
            started_at = time.perf_counter()
            try:
                patch = node(state)
            except Exception as exc:
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                repository.mark_node_failed(node_name, str(exc), duration_ms)
                raise
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            repository.mark_node_finished(node_name, patch, duration_ms)
            return patch

        return wrapped

    def resume(self, request: RunRequest) -> dict[str, Any]:
        return self.run(
            RunRequest(
                flow_id=request.flow_id,
                tenant_id=request.tenant_id,
                batch_id=request.batch_id,
                trigger_mode=request.trigger_mode,
                source_url=request.source_url,
                topic_context=request.topic_context,
                additional_instruction=request.additional_instruction,
                tenant_runtime_config=request.tenant_runtime_config,
                resume=True,
            )
        )
