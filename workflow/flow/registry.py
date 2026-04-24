from __future__ import annotations

from typing import Any, Callable

from workflow.flow.content_collect.graph import build_content_collect_graph
from workflow.flow.content_create.graph import (
    build_content_create_original_graph,
    build_content_create_rewrite_graph,
)
from workflow.flow.daily_report.graph import build_daily_report_graph


RUN_PARAM_CATALOG: dict[str, dict[str, Any]] = {
    "tenant_id": {
        "type": "string",
        "description": "Optional explicit tenant ID. When omitted, server resolves tenant from X-API-Key.",
        "default": None,
    },
    "batch_id": {
        "type": "string",
        "description": "Optional batch ID. If omitted, runtime generates one from current time.",
        "default": None,
    },
    "source_url": {
        "type": "string",
        "description": "Source URL consumed by rewrite flows. Required when the flow needs source content.",
        "default": "",
    },
}

FLOW_DEFINITIONS: dict[str, dict[str, Any]] = {
    "content-collect": {
        "builder": build_content_collect_graph,
        "name": "内容采集",
        "description": "采集行业关键词、行业报告、对标账号、热点和选题库。",
        "params": ("tenant_id", "batch_id"),
        "required": (),
    },
    "content-create-original": {
        "builder": build_content_create_original_graph,
        "name": "原创内容生成",
        "description": "基于营销策划方案和日报生成原创文案与配图。",
        "params": ("tenant_id", "batch_id"),
        "required": (),
    },
    "content-create-rewrite": {
        "builder": build_content_create_rewrite_graph,
        "name": "二创内容生成",
        "description": "基于来源链接抓取对标笔记，生成二创文案与配图。",
        "params": ("tenant_id", "batch_id", "source_url"),
        "required": ("source_url",),
    },
    "daily-report": {
        "builder": build_daily_report_graph,
        "name": "日报生成",
        "description": "汇总业务数据并生成日报内容。",
        "params": ("tenant_id", "batch_id"),
        "required": (),
    },
}


def _build_run_request_schema(param_names: tuple[str, ...], required_names: tuple[str, ...]) -> dict[str, Any]:
    required_set = set(required_names)
    properties: dict[str, dict[str, Any]] = {}
    for name in param_names:
        field_schema = dict(RUN_PARAM_CATALOG[name])
        field_schema["required"] = name in required_set
        properties[name] = field_schema
    return {
        "type": "object",
        "properties": properties,
        "required": list(required_names),
    }


def build_flow_definition(runtime) -> dict[str, Any]:
    flow_definition = FLOW_DEFINITIONS.get(runtime.flow_id)
    if flow_definition is None:
        raise ValueError(f"unknown flow: {runtime.flow_id}")
    builder = flow_definition["builder"]
    return builder(runtime)


def list_flow_definitions() -> list[dict[str, Any]]:
    flow_items: list[dict[str, Any]] = []
    for flow_id in sorted(FLOW_DEFINITIONS.keys()):
        flow_definition = FLOW_DEFINITIONS[flow_id]
        flow_items.append(
            {
                "id": flow_id,
                "name": flow_definition["name"],
                "description": flow_definition["description"],
                "run_request_schema": _build_run_request_schema(
                    flow_definition["params"],
                    flow_definition["required"],
                ),
            }
        )
    return flow_items


def has_flow_definition(flow_id: str) -> bool:
    return flow_id in FLOW_DEFINITIONS


def get_flow_node_ids(flow_id: str) -> list[str]:
    flow_definition = FLOW_DEFINITIONS.get(flow_id)
    if flow_definition is None:
        raise ValueError(f"unknown flow: {flow_id}")
    builder = flow_definition["builder"]
    graph = builder(None)
    nodes = graph.get("nodes", {})
    if not isinstance(nodes, dict):
        return []
    return list(nodes.keys())
