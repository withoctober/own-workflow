from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RunFlowRequest(BaseModel):
    tenant_id: str | None = Field(default=None, description="Optional explicit tenant ID. When omitted, server resolves tenant from X-API-Key.")
    batch_id: str | None = Field(default=None, description="Optional batch ID. If omitted, runtime generates one from current time.")
    source_url: str = Field(default="", description="Required for content-create-rewrite flow. Ignored by flows that do not need source content.")


class ScheduleRequestPayload(BaseModel):
    source_url: str = Field(default="", description="Optional source_url forwarded to workflow runtime.")


class DatasetTableRowRequest(BaseModel):
    record_id: str = Field(default="", description="Optional record id. Leave empty when creating a new row.")
    payload: dict[str, Any] = Field(default_factory=dict, description="Structured row payload stored in the dataset.")


class DatasetTableListResponse(BaseModel):
    tenant_id: str
    dataset_key: str
    dataset_name: str
    fields: list[str]
    rows: list[dict[str, Any]]


class DatasetTableRowResponse(BaseModel):
    tenant_id: str
    dataset_key: str
    dataset_name: str
    row: dict[str, Any]


class DatasetTableCatalogItemResponse(BaseModel):
    dataset_key: str
    dataset_name: str
    fields: list[str]


class DatasetTableCatalogResponse(BaseModel):
    tables: list[DatasetTableCatalogItemResponse]


class WorkflowRunListItemResponse(BaseModel):
    tenant_id: str
    flow_id: str
    batch_id: str
    source_url: str
    status: str
    current_node: str
    resume_count: int
    completed_node_count: int
    error_count: int
    last_message: str
    last_error: str
    started_at: str
    updated_at: str
    finished_at: str
    run_path: str


class WorkflowRunListResponse(BaseModel):
    tenant_id: str
    total: int
    limit: int
    offset: int
    runs: list[WorkflowRunListItemResponse]


class UpsertTenantFlowScheduleRequest(BaseModel):
    cron: str = Field(min_length=1, description="Cron expression with five fields: minute hour day month weekday.")
    is_active: bool = Field(default=True, description="Whether the schedule is enabled.")
    batch_id_prefix: str = Field(default="", description="Optional batch id prefix for scheduled runs.")
    request_payload: ScheduleRequestPayload = Field(
        default_factory=ScheduleRequestPayload,
        description="Optional workflow request payload forwarded to scheduled execution.",
    )


class CreateTenantRequest(BaseModel):
    tenant_name: str = Field(min_length=1, description="Display name for the tenant.")
    api_key: str = Field(min_length=1, description="Tenant scoped API key required by protected endpoints.")
    is_active: bool = Field(default=True, description="Whether the tenant is active.")
    default_llm_model: str = Field(default="", description="Optional tenant default LLM model.")
    timeout_seconds: int = Field(default=30, ge=1, description="Default timeout for tenant scoped integrations.")
    max_retries: int = Field(default=2, ge=0, description="Default retries for tenant scoped integrations.")


class TenantResponse(BaseModel):
    tenant_id: str
    tenant_name: str
    api_key: str
    is_active: bool
    default_llm_model: str
    timeout_seconds: int
    max_retries: int


class TenantFlowScheduleResponse(BaseModel):
    tenant_id: str
    flow_id: str
    cron: str
    is_active: bool
    batch_id_prefix: str
    request_payload: dict[str, Any]
    next_run_at: str
    last_run_at: str
    last_status: str
    last_error: str
    last_batch_id: str
    is_running: bool


class TenantFlowScheduleListResponse(BaseModel):
    schedules: list[TenantFlowScheduleResponse]


class ApiResponse(BaseModel):
    code: int = Field(description="Business status code. 0 means success.")
    message: str = Field(description="Human readable response message.")
    data: Any = Field(default="", description="Response payload or error details.")


def success_response(data: Any, message: str = "ok") -> dict[str, Any]:
    """Build a normalized success response payload."""
    return ApiResponse(code=0, message=message, data=data).model_dump()


def error_response(code: int, message: str, data: Any = "") -> dict[str, Any]:
    """Build a normalized error response payload."""
    return ApiResponse(code=code, message=message, data=data).model_dump()
