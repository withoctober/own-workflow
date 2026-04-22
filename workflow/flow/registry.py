from __future__ import annotations

from typing import Any, Callable

from workflow.flow.content_collect.graph import build_content_collect_graph
from workflow.flow.content_create.graph import (
    build_content_create_original_graph,
    build_content_create_rewrite_graph,
)
from workflow.flow.daily_report.graph import build_daily_report_graph


FLOW_BUILDERS: dict[str, Callable[[Any], dict[str, Any]]] = {
    "content-collect": build_content_collect_graph,
    "daily-report": build_daily_report_graph,
    "content-create-original": build_content_create_original_graph,
    "content-create-rewrite": build_content_create_rewrite_graph,
}


def build_flow_definition(runtime) -> dict[str, Any]:
    builder = FLOW_BUILDERS.get(runtime.flow_id)
    if builder is None:
        raise ValueError(f"unknown flow: {runtime.flow_id}")
    return builder(runtime)


def list_flow_definitions() -> list[dict[str, Any]]:
    return [{"id": flow_id} for flow_id in sorted(FLOW_BUILDERS.keys())]
