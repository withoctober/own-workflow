from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class Tenant:
    id: str
    tenant_id: str
    tenant_name: str
    api_key: str
    is_active: bool
    default_llm_model: str
    api_mode: str
    api_ref: dict[str, Any]
    timeout_seconds: int
    max_retries: int


@dataclass
class TenantFlowSchedule:
    id: str
    tenant_pk: str
    tenant_id: str
    flow_id: str
    cron_expr: str
    is_active: bool
    request_payload: dict[str, Any]
    batch_id_prefix: str
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_status: str
    last_error: str
    last_batch_id: str
    is_running: bool
    locked_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass
class StoreEntry:
    id: str
    tenant_id: str
    dataset_key: str
    entry_type: str
    record_key: str
    title: str
    batch_id: str
    sort_order: int
    content_text: str
    payload: dict[str, Any]
    schema_version: int
    source_ref: str
    is_deleted: bool
    created_at: datetime | None
    updated_at: datetime | None


@dataclass
class WorkflowRun:
    id: str
    tenant_id: str
    flow_id: str
    batch_id: str
    source_url: str
    status: str
    current_node: str
    current_node_index: int
    total_node_count: int
    resume_count: int
    completed_node_count: int
    error_count: int
    last_message: str
    last_error: str
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass
class Artifact:
    id: str
    tenant_id: str
    flow_id: str
    batch_id: str
    workflow_run_id: str
    artifact_type: str
    title: str
    content: str
    tags: str
    cover_prompt: str
    cover_url: str
    image_prompts: list[str]
    image_urls: list[str]
    source_url: str
    payload: dict[str, Any]
    created_at: datetime | None
    updated_at: datetime | None
