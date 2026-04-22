from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import time
from typing import Any

from langgraph.graph import END, START, StateGraph

from workflow.flow.registry import build_flow_definition, list_flow_definitions
from workflow.runtime.context import RuntimeContext
from workflow.runtime.persistence import StateRepository
from workflow.runtime.tenant import TenantRuntimeConfig
from workflow.settings import WorkflowSettings
from workflow.state import WorkflowState


@dataclass
class RunRequest:
    flow_id: str
    tenant_id: str = "default"
    batch_id: str | None = None
    source_url: str = ""
    tenant_runtime_config: TenantRuntimeConfig | None = None
    resume: bool = False


class GraphRuntime:
    def __init__(self, settings: WorkflowSettings) -> None:
        self.settings = settings

    def list_flows(self) -> list[dict[str, Any]]:
        return list_flow_definitions()

    def build_context(self, request: RunRequest) -> RuntimeContext:
        batch_id = request.batch_id or datetime.now().strftime("%Y%m%d%H%M%S")
        return RuntimeContext(
            settings=self.settings,
            flow_id=request.flow_id,
            batch_id=batch_id,
            tenant_id=request.tenant_id,
            source_url=request.source_url,
            tenant_runtime_config=request.tenant_runtime_config,
        )

    def run(self, request: RunRequest) -> dict[str, Any]:
        context = self.build_context(request)
        repository = StateRepository(context)
        if request.resume:
            state = repository.prepare_resume()
        else:
            state = repository.mark_run_started()
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
                source_url=request.source_url,
                tenant_runtime_config=request.tenant_runtime_config,
                resume=True,
            )
        )
