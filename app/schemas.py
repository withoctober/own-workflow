from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator
from pydantic_core import PydanticCustomError


class RunFlowRequest(BaseModel):
    tenant_id: str | None = Field(default=None, description="Optional explicit tenant ID. When omitted, server resolves tenant from X-API-Key.")
    batch_id: str | None = Field(default=None, description="Optional batch ID. If omitted, runtime generates one from current time.")
    source_url: str = Field(default="", description="Required for content-create-rewrite flow. Ignored by flows that do not need source content.")
    topic_context: dict[str, Any] = Field(default_factory=dict, description="Selected topic context forwarded to content generation flows.")
    additional_instruction: str = Field(default="", description="User supplied instruction forwarded to content generation flows.")


class ScheduleRequestPayload(BaseModel):
    source_url: str = Field(default="", description="Optional source_url forwarded to workflow runtime.")
    topic_context: dict[str, Any] = Field(default_factory=dict, description="Optional selected topic context forwarded to workflow runtime.")
    additional_instruction: str = Field(default="", description="Optional user supplied instruction forwarded to workflow runtime.")


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
    trigger_mode: str
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


class ArtifactResponse(BaseModel):
    artifact_id: str
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
    created_at: str
    updated_at: str


class ArtifactListResponse(BaseModel):
    tenant_id: str
    total: int
    limit: int
    offset: int
    items: list[ArtifactResponse]


class ArtifactUpdateRequest(BaseModel):
    title: str | None = Field(default=None, description="Optional artifact title override.")
    content: str | None = Field(default=None, description="Optional artifact content override.")
    tags: str | None = Field(default=None, description="Optional serialized tags string.")
    cover_prompt: str | None = Field(default=None, description="Optional cover prompt override.")
    cover_url: str | None = Field(default=None, description="Optional cover image URL override.")
    image_prompts: list[str] | None = Field(default=None, description="Optional image prompt list override.")
    image_urls: list[str] | None = Field(default=None, description="Optional gallery image URL list override.")
    payload: dict[str, Any] | None = Field(default=None, description="Optional full artifact payload override.")


class ArtifactRegenerateImageRequest(BaseModel):
    image_index: int = Field(ge=0, description="Zero-based gallery index. 0 targets cover, 1+ targets image_urls[index-1].")
    prompt: str | None = Field(default=None, description="Optional prompt override for the selected image.")


class ArtifactPreviewImageEditRequest(BaseModel):
    image_index: int = Field(ge=0, description="Zero-based gallery index. 0 targets cover, 1+ targets image_urls[index-1].")
    prompt: str | None = Field(default=None, description="Optional prompt override for the selected image.")


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
    api_mode: str = Field(default="system", description="Credential source mode: system or custom.")
    api_ref: dict[str, Any] = Field(default_factory=dict, description="Custom API config map using env-style keys.")
    timeout_seconds: int = Field(default=600, ge=1, description="Default timeout for tenant scoped integrations.")
    max_retries: int = Field(default=2, ge=0, description="Default retries for tenant scoped integrations.")

    @model_validator(mode="after")
    def validate_api_mode_and_ref(self) -> "CreateTenantRequest":
        normalized_mode = str(self.api_mode or "system").strip().lower() or "system"
        self.api_mode = normalized_mode
        if normalized_mode not in {"system", "custom"}:
            raise PydanticCustomError("api_mode_invalid", "api_mode 仅支持 system 或 custom")
        if normalized_mode == "system":
            return self

        required_keys = [
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "OPENAI_MODEL",
            "TIKHUB_API_KEY",
            "IMAGE_PROVIDER",
            "IMAGE_API_BASE_URL",
            "IMAGE_API_KEY",
            "IMAGE_API_MODEL",
        ]
        missing = [key for key in required_keys if not str(self.api_ref.get(key, "")).strip()]
        if missing:
            missing_text = ", ".join(missing)
            raise PydanticCustomError(
                "api_ref_incomplete",
                "api_mode=custom 时必须提供完整 api_ref，缺少: {missing}",
                {"missing": missing_text},
            )
        return self


class TenantResponse(BaseModel):
    tenant_id: str
    tenant_name: str
    api_key: str
    is_active: bool
    default_llm_model: str
    api_mode: str
    api_ref: dict[str, Any]
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
