from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RunFlowRequest(BaseModel):
    tenant_id: str = Field(default="default", min_length=1, description="Feishu tenant ID. Defaults to config.default_tenant.")
    batch_id: str | None = Field(default=None, description="Optional batch ID. If omitted, runtime generates one from current time.")
    source_url: str = Field(default="", description="Required for content-create-rewrite flow. Ignored by flows that do not need source content.")


class ScheduleRequestPayload(BaseModel):
    source_url: str = Field(default="", description="Optional source_url forwarded to workflow runtime.")


class UpsertTenantFlowScheduleRequest(BaseModel):
    cron: str = Field(min_length=1, description="Cron expression with five fields: minute hour day month weekday.")
    is_active: bool = Field(default=True, description="Whether the schedule is enabled.")
    batch_id_prefix: str = Field(default="", description="Optional batch id prefix for scheduled runs.")
    request_payload: ScheduleRequestPayload = Field(
        default_factory=ScheduleRequestPayload,
        description="Optional workflow request payload forwarded to scheduled execution.",
    )


class UpsertTenantRequest(BaseModel):
    tenant_name: str = Field(min_length=1, description="Display name for the tenant.")
    is_active: bool = Field(default=True, description="Whether the tenant is active.")
    default_llm_model: str = Field(default="", description="Optional tenant default LLM model.")
    timeout_seconds: int = Field(default=30, ge=1, description="Default timeout for tenant scoped integrations.")
    max_retries: int = Field(default=2, ge=0, description="Default retries for tenant scoped integrations.")


class CreateTenantRequest(BaseModel):
    tenant_name: str = Field(min_length=1, description="Display name for the tenant.")
    is_active: bool = Field(default=True, description="Whether the tenant is active.")
    default_llm_model: str = Field(default="", description="Optional tenant default LLM model.")
    timeout_seconds: int = Field(default=30, ge=1, description="Default timeout for tenant scoped integrations.")
    max_retries: int = Field(default=2, ge=0, description="Default retries for tenant scoped integrations.")


class UpsertTenantFeishuConfigRequest(BaseModel):
    tenant_name: str = Field(min_length=1, description="Display name for the tenant.")
    app_id: str = Field(default="", description="Feishu app id stored in plain text.")
    app_secret: str = Field(default="", description="Feishu app secret stored in plain text.")
    tenant_access_token: str = Field(default="", description="Optional fixed tenant access token.")
    base_url: str = Field(min_length=1, description="Feishu bitable URL.")
    industry_report_url: str = Field(min_length=1, description="Feishu docx/wiki URL for 行业报告.")
    marketing_plan_url: str = Field(min_length=1, description="Feishu docx/wiki URL for 营销策划方案.")
    keyword_matrix_url: str = Field(min_length=1, description="Feishu docx/wiki URL for 关键词矩阵.")
    default_llm_model: str = Field(default="", description="Optional tenant default LLM model.")
    timeout_seconds: int = Field(default=30, ge=1, description="Default timeout for tenant scoped integrations.")
    max_retries: int = Field(default=2, ge=0, description="Default retries for tenant scoped integrations.")


class TenantResponse(BaseModel):
    tenant_id: str
    tenant_name: str
    is_active: bool
    default_llm_model: str
    timeout_seconds: int
    max_retries: int


class TenantFeishuConfigResponse(BaseModel):
    tenant_id: str
    tenant_name: str
    is_active: bool
    default_llm_model: str
    timeout_seconds: int
    max_retries: int
    app_id: str
    app_secret: str
    tenant_access_token: str
    config: dict[str, Any]


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
