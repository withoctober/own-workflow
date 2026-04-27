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
        "description": "粘贴一条想参考的小红书笔记链接，系统会围绕它做二创改写。",
        "default": "",
    },
}

FLOW_DEFINITIONS: dict[str, dict[str, Any]] = {
    "content-collect": {
        "builder": build_content_collect_graph,
        "name": "经营资料体检",
        "description": "先把品牌、行业、对标账号和热点素材整理好，让后续内容生成有依据。",
        "step": 1,
        "scene": "资料准备",
        "primary_action": "开始整理资料",
        "user_hint": "适合第一次使用，或品牌资料更新后重新跑一遍。",
        "xhs_stage": "先搭好账号定位和内容素材库",
        "params": ("tenant_id", "batch_id"),
        "required": (),
    },
    "content-create-original": {
        "builder": build_content_create_original_graph,
        "name": "原创笔记生成",
        "description": "基于你的品牌资料、营销方案和日报选题，生成可发布的小红书图文笔记。",
        "step": 4,
        "scene": "发笔记",
        "primary_action": "生成原创笔记",
        "user_hint": "没有参考链接时选这个，适合日常批量产出。",
        "xhs_stage": "像发小红书一样生成封面、标题、正文和标签",
        "params": ("tenant_id", "batch_id"),
        "required": (),
    },
    "content-create-rewrite": {
        "builder": build_content_create_rewrite_graph,
        "name": "爆款参考改写",
        "description": "粘贴一条参考笔记链接，系统提取结构后生成适合你品牌的二创内容。",
        "step": 4,
        "scene": "追热点 / 拆爆款",
        "primary_action": "粘贴链接改写",
        "user_hint": "看到同行爆款、热点案例时选这个，需要填写 source_url。",
        "xhs_stage": "参考爆款但不照抄，转成自己的内容表达",
        "params": ("tenant_id", "batch_id", "source_url"),
        "required": ("source_url",),
    },
    "daily-report": {
        "builder": build_daily_report_graph,
        "name": "今日选题日报",
        "description": "结合近期数据和营销方向，生成今天优先写什么、为什么写、怎么写。",
        "step": 3,
        "scene": "定选题",
        "primary_action": "生成今日日报",
        "user_hint": "每天开始创作前先看它，降低不知道发什么的成本。",
        "xhs_stage": "把今天要发的内容任务排出来",
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
                "step": flow_definition["step"],
                "scene": flow_definition["scene"],
                "primary_action": flow_definition["primary_action"],
                "user_hint": flow_definition["user_hint"],
                "xhs_stage": flow_definition["xhs_stage"],
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
