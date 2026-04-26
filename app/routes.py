from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_runtime, get_settings, load_run_state, require_tenant_api_key
from model import (
    delete_tenant_flow_schedule,
    ensure_postgres_tables,
    generate_tenant_id,
    get_artifact,
    get_tenant_flow_schedule,
    get_tenant_runtime_config,
    get_tenant_by_id,
    insert_store_rows,
    list_artifacts,
    list_workflow_runs,
    list_tenant_flow_schedules,
    list_tenants,
    list_store_entries,
    postgres_enabled,
    soft_delete_store_entry,
    upsert_tenant_flow_schedule,
    upsert_tenant,
    update_store_rows,
)
from app.schemas import (
    ArtifactListResponse,
    ArtifactResponse,
    CreateTenantRequest,
    DatasetTableCatalogItemResponse,
    DatasetTableCatalogResponse,
    DatasetTableListResponse,
    DatasetTableRowRequest,
    DatasetTableRowResponse,
    RunFlowRequest,
    TenantFlowScheduleListResponse,
    TenantFlowScheduleResponse,
    TenantResponse,
    UpsertTenantFlowScheduleRequest,
    WorkflowRunListItemResponse,
    WorkflowRunListResponse,
    success_response,
)
from workflow.flow.registry import has_flow_definition
from workflow.runtime.tenant import TenantRuntimeConfig
from workflow.runtime.engine import GraphRuntime, RunRequest
from workflow.runtime.scheduler import compute_next_run_at, normalize_batch_id_prefix, validate_cron_expression
from workflow.settings import WorkflowSettings
from workflow.store.database import get_dataset_definition, get_table_dataset_definition, list_display_dataset_definitions
from workflow.store import StoreError


router = APIRouter()

_ENSURED_DATABASE_URLS: set[str] = set()


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat()


def build_schedule_response(schedule) -> TenantFlowScheduleResponse:
    return TenantFlowScheduleResponse(
        tenant_id=schedule.tenant_id,
        flow_id=schedule.flow_id,
        cron=schedule.cron_expr,
        is_active=schedule.is_active,
        batch_id_prefix=schedule.batch_id_prefix,
        request_payload=schedule.request_payload,
        next_run_at=_format_datetime(schedule.next_run_at),
        last_run_at=_format_datetime(schedule.last_run_at),
        last_status=schedule.last_status,
        last_error=schedule.last_error,
        last_batch_id=schedule.last_batch_id,
        is_running=schedule.is_running,
    )


def require_database(settings: WorkflowSettings) -> str:
    if not postgres_enabled(settings.database_url):
        raise HTTPException(status_code=400, detail="缺少 DATABASE_URL，当前未启用 PostgreSQL 配置")
    if settings.database_url not in _ENSURED_DATABASE_URLS:
        ensure_postgres_tables(settings.database_url)
        _ENSURED_DATABASE_URLS.add(settings.database_url)
    return settings.database_url


def _resolve_tenant_id(explicit_tenant_id: str | None, authenticated_tenant_id: str) -> str:
    tenant_id = str(explicit_tenant_id or "").strip()
    return tenant_id or authenticated_tenant_id


def _build_table_row(entry) -> dict:
    row = {"record_id": entry.record_key}
    row.update(entry.payload if isinstance(entry.payload, dict) else {})
    return row


def _build_workflow_run_item(entry) -> WorkflowRunListItemResponse:
    return WorkflowRunListItemResponse(
        tenant_id=entry.tenant_id,
        flow_id=entry.flow_id,
        batch_id=entry.batch_id,
        trigger_mode=entry.trigger_mode,
        source_url=entry.source_url,
        status=entry.status,
        current_node=entry.current_node,
        current_node_index=entry.current_node_index,
        total_node_count=entry.total_node_count,
        resume_count=entry.resume_count,
        completed_node_count=entry.completed_node_count,
        error_count=entry.error_count,
        last_message=entry.last_message,
        last_error=entry.last_error,
        started_at=_format_datetime(entry.started_at),
        updated_at=_format_datetime(entry.updated_at),
        finished_at=_format_datetime(entry.finished_at),
        run_path=f"/api/flows/{entry.flow_id}/runs/{entry.batch_id}",
    )


def _build_artifact_item(entry) -> ArtifactResponse:
    return ArtifactResponse(
        artifact_id=entry.id,
        tenant_id=entry.tenant_id,
        flow_id=entry.flow_id,
        batch_id=entry.batch_id,
        workflow_run_id=entry.workflow_run_id,
        artifact_type=entry.artifact_type,
        title=entry.title,
        content=entry.content,
        tags=entry.tags,
        cover_prompt=entry.cover_prompt,
        cover_url=entry.cover_url,
        image_prompts=entry.image_prompts,
        image_urls=entry.image_urls,
        source_url=entry.source_url,
        payload=entry.payload,
        created_at=_format_datetime(entry.created_at),
        updated_at=_format_datetime(entry.updated_at),
    )


def _require_table_dataset(dataset_key: str):
    dataset = get_table_dataset_definition(dataset_key)
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"unknown table dataset: {dataset_key}")
    return dataset


def _require_display_dataset(dataset_key: str):
    dataset = get_dataset_definition(dataset_key)
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"unknown dataset: {dataset_key}")
    return dataset


def _dataset_fields(dataset) -> list[str]:
    if dataset.kind == "doc":
        return ["文档"]
    return list(dataset.fields)


def _build_doc_row(entry) -> dict:
    return {
        "record_id": entry.record_key or "__doc__",
        "文档": entry.content_text,
    }


@router.get("/health")
def health() -> dict:
    return success_response({"status": "ok"})


@router.get("/tenants")
def get_tenants(
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
) -> dict:
    database_url = require_database(settings)
    tenants = list_tenants(database_url)
    data = {
        "tenants": [
            TenantResponse(
                tenant_id=item.tenant_id,
                tenant_name=item.tenant_name,
                api_key=item.api_key,
                is_active=item.is_active,
                default_llm_model=item.default_llm_model,
                api_mode=item.api_mode,
                api_ref=item.api_ref,
                timeout_seconds=item.timeout_seconds,
                max_retries=item.max_retries,
            )
            for item in tenants
        ]
    }
    return success_response(data)


@router.post("/tenants")
def create_tenant(
    request: CreateTenantRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
) -> dict:
    database_url = require_database(settings)
    tenant = upsert_tenant(
        database_url,
        tenant_id=generate_tenant_id(database_url, request.tenant_name),
        tenant_name=request.tenant_name,
        api_key=request.api_key,
        is_active=request.is_active,
        default_llm_model=request.default_llm_model,
        api_mode=request.api_mode,
        api_ref=request.api_ref if request.api_mode == "custom" else {},
        timeout_seconds=request.timeout_seconds,
        max_retries=request.max_retries,
    )
    return success_response(
        TenantResponse(
            tenant_id=tenant.tenant_id,
            tenant_name=tenant.tenant_name,
            api_key=tenant.api_key,
            is_active=tenant.is_active,
            default_llm_model=tenant.default_llm_model,
            api_mode=tenant.api_mode,
            api_ref=tenant.api_ref,
            timeout_seconds=tenant.timeout_seconds,
            max_retries=tenant.max_retries,
        ).model_dump()
    )


def get_tenant_schedules(
    tenant_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    database_url = require_database(settings)
    tenant = get_tenant_by_id(database_url, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    schedules = list_tenant_flow_schedules(database_url, tenant_id)
    return success_response(
        TenantFlowScheduleListResponse(
            schedules=[build_schedule_response(item) for item in schedules],
        ).model_dump()
    )


def list_tenant_tables(
    tenant_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    database_url = require_database(settings)
    tenant = get_tenant_by_id(database_url, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    tables = [
        DatasetTableCatalogItemResponse(
            dataset_key=dataset.dataset_key,
            dataset_name=dataset.name,
            fields=_dataset_fields(dataset),
        )
        for dataset in list_display_dataset_definitions()
    ]
    return success_response(DatasetTableCatalogResponse(tables=tables).model_dump())


def get_tenant_table_rows(
    tenant_id: str,
    dataset_key: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
    limit: int | None = None,
    offset: int = 0,
    order: str = "asc",
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    database_url = require_database(settings)
    tenant = get_tenant_by_id(database_url, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    dataset = _require_display_dataset(dataset_key)
    if dataset.kind == "doc":
        entries = list_store_entries(
            database_url,
            tenant_id=tenant_id,
            dataset_key=dataset.dataset_key,
            entry_type="doc",
            limit=limit,
            offset=offset,
            order=order,
        )
        response = DatasetTableListResponse(
            tenant_id=tenant_id,
            dataset_key=dataset.dataset_key,
            dataset_name=dataset.name,
            fields=_dataset_fields(dataset),
            rows=[_build_doc_row(entry) for entry in entries],
        )
        return success_response(response.model_dump())

    entries = list_store_entries(
        database_url,
        tenant_id=tenant_id,
        dataset_key=dataset.dataset_key,
        entry_type="row",
        limit=limit,
        offset=offset,
        order=order,
    )
    response = DatasetTableListResponse(
        tenant_id=tenant_id,
        dataset_key=dataset.dataset_key,
        dataset_name=dataset.name,
        fields=list(dataset.fields),
        rows=[_build_table_row(entry) for entry in entries],
    )
    return success_response(response.model_dump())


def create_tenant_table_row(
    tenant_id: str,
    dataset_key: str,
    request: DatasetTableRowRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    database_url = require_database(settings)
    tenant = get_tenant_by_id(database_url, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    dataset = _require_table_dataset(dataset_key)
    payload = dict(request.payload)
    if request.record_id.strip():
        payload["record_id"] = request.record_id.strip()
    inserted = insert_store_rows(
        database_url,
        tenant_id=tenant_id,
        dataset_key=dataset.dataset_key,
        rows=[payload],
    )
    if not inserted:
        raise HTTPException(status_code=400, detail="failed to create table row")
    response = DatasetTableRowResponse(
        tenant_id=tenant_id,
        dataset_key=dataset.dataset_key,
        dataset_name=dataset.name,
        row=_build_table_row(inserted[0]),
    )
    return success_response(response.model_dump())


def update_tenant_table_row(
    tenant_id: str,
    dataset_key: str,
    record_id: str,
    request: DatasetTableRowRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    database_url = require_database(settings)
    tenant = get_tenant_by_id(database_url, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    dataset = _require_table_dataset(dataset_key)
    payload = dict(request.payload)
    payload["record_id"] = record_id
    updated = update_store_rows(
        database_url,
        tenant_id=tenant_id,
        dataset_key=dataset.dataset_key,
        rows=[payload],
    )
    if not updated:
        raise HTTPException(status_code=404, detail="table row not found")
    response = DatasetTableRowResponse(
        tenant_id=tenant_id,
        dataset_key=dataset.dataset_key,
        dataset_name=dataset.name,
        row=_build_table_row(updated[0]),
    )
    return success_response(response.model_dump())


def delete_tenant_table_row(
    tenant_id: str,
    dataset_key: str,
    record_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    database_url = require_database(settings)
    tenant = get_tenant_by_id(database_url, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    dataset = _require_table_dataset(dataset_key)
    deleted = soft_delete_store_entry(
        database_url,
        tenant_id=tenant_id,
        dataset_key=dataset.dataset_key,
        entry_type="row",
        record_key=record_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="table row not found")
    return success_response(
        {
            "tenant_id": tenant_id,
            "dataset_key": dataset.dataset_key,
            "record_id": record_id,
            "deleted": True,
        }
    )


def get_tenant_schedule(
    tenant_id: str,
    flow_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    database_url = require_database(settings)
    tenant = get_tenant_by_id(database_url, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    schedule = get_tenant_flow_schedule(database_url, tenant_id, flow_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="tenant flow schedule not found")
    return success_response(build_schedule_response(schedule).model_dump())


def put_tenant_schedule(
    tenant_id: str,
    flow_id: str,
    request: UpsertTenantFlowScheduleRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    database_url = require_database(settings)
    tenant = get_tenant_by_id(database_url, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    if not has_flow_definition(flow_id):
        raise HTTPException(status_code=404, detail=f"unknown flow: {flow_id}")
    validate_cron_expression(request.cron)
    next_run_at = compute_next_run_at(request.cron) if request.is_active else None
    request_payload = request.request_payload.model_dump(exclude_defaults=True, exclude_none=True)
    schedule = upsert_tenant_flow_schedule(
        database_url,
        tenant_pk=tenant.id,
        tenant_id=tenant_id,
        flow_id=flow_id,
        cron_expr=request.cron,
        is_active=request.is_active,
        request_payload=request_payload,
        batch_id_prefix=normalize_batch_id_prefix(request.batch_id_prefix),
        next_run_at=next_run_at,
    )
    return success_response(build_schedule_response(schedule).model_dump())


def delete_tenant_schedule(
    tenant_id: str,
    flow_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    database_url = require_database(settings)
    tenant = get_tenant_by_id(database_url, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    deleted = delete_tenant_flow_schedule(database_url, tenant_id, flow_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="tenant flow schedule not found")
    return success_response({"tenant_id": tenant_id, "flow_id": flow_id, "deleted": True})


def trigger_tenant_schedule(
    tenant_id: str,
    flow_id: str,
    runtime: Annotated[GraphRuntime, Depends(get_runtime)],
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    try:
        tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
        database_url = require_database(settings)
        tenant = get_tenant_by_id(database_url, tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="tenant not found")
        schedule = get_tenant_flow_schedule(database_url, tenant_id, flow_id)
        if schedule is None:
            raise HTTPException(status_code=404, detail="tenant flow schedule not found")
        runtime_payload = get_tenant_runtime_config(database_url, tenant_id)
        if runtime_payload is None:
            raise HTTPException(status_code=400, detail=f"PostgreSQL 中未找到 tenant_id={tenant_id} 的运行配置")
        request_payload = schedule.request_payload if isinstance(schedule.request_payload, dict) else {}
        result = runtime.run(
            RunRequest(
                flow_id=flow_id,
                tenant_id=tenant_id,
                trigger_mode="manual",
                source_url=str(request_payload.get("source_url") or ""),
                topic_context=request_payload.get("topic_context") if isinstance(request_payload.get("topic_context"), dict) else {},
                additional_instruction=str(request_payload.get("additional_instruction") or ""),
                tenant_runtime_config=TenantRuntimeConfig(payload=runtime_payload),
            )
        )
        return success_response(result)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/flows")
def list_flows(
    runtime: Annotated[GraphRuntime, Depends(get_runtime)],
    _: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return success_response({"flows": runtime.list_flows()})


@router.post("/flows/{flow_id}/runs")
def run_flow(
    flow_id: str,
    request: RunFlowRequest,
    runtime: Annotated[GraphRuntime, Depends(get_runtime)],
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    try:
        tenant_id = _resolve_tenant_id(request.tenant_id, authenticated_tenant_id)
        database_url = require_database(settings)
        runtime_payload = get_tenant_runtime_config(database_url, tenant_id)
        if runtime_payload is None:
            raise HTTPException(status_code=400, detail=f"PostgreSQL 中未找到 tenant_id={tenant_id} 的运行配置")
        result = runtime.enqueue(
            RunRequest(
                flow_id=flow_id,
                tenant_id=tenant_id,
                batch_id=request.batch_id,
                trigger_mode="manual",
                source_url=request.source_url,
                topic_context=request.topic_context,
                additional_instruction=request.additional_instruction,
                tenant_runtime_config=TenantRuntimeConfig(payload=runtime_payload),
            )
        )
        return success_response(
            {
                "status": result["status"],
                "tenant_id": tenant_id,
                "flow_id": flow_id,
                "batch_id": result["batch_id"],
                "run_path": f"/api/flows/{flow_id}/runs/{result['batch_id']}",
                "current_node": result.get("current_node", ""),
                "current_node_index": result.get("current_node_index", 0),
                "total_node_count": result.get("total_node_count", 0),
                "completed_node_count": len(result.get("completed_nodes", [])),
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def resume_flow(
    flow_id: str,
    tenant_id: str,
    batch_id: str,
    runtime: Annotated[GraphRuntime, Depends(get_runtime)],
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    try:
        tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
        database_url = require_database(settings)
        runtime_payload = get_tenant_runtime_config(database_url, tenant_id)
        if runtime_payload is None:
            raise HTTPException(status_code=400, detail=f"PostgreSQL 中未找到 tenant_id={tenant_id} 的运行配置")
        state = load_run_state(settings, flow_id, tenant_id, batch_id)
        result = runtime.enqueue(
            RunRequest(
                flow_id=flow_id,
                tenant_id=tenant_id,
                batch_id=batch_id,
                trigger_mode=str(state.get("trigger_mode") or ""),
                source_url=str(state.get("source_url") or ""),
                topic_context=state.get("topic_context") if isinstance(state.get("topic_context"), dict) else {},
                additional_instruction=str(state.get("additional_instruction") or ""),
                tenant_runtime_config=TenantRuntimeConfig(payload=runtime_payload),
                resume=True,
            )
        )
        return success_response(
            {
                "status": result["status"],
                "tenant_id": tenant_id,
                "flow_id": flow_id,
                "batch_id": batch_id,
                "run_path": f"/api/flows/{flow_id}/runs/{batch_id}",
                "resume_count": result.get("resume_count", 0),
                "current_node": result.get("current_node", ""),
                "current_node_index": result.get("current_node_index", 0),
                "total_node_count": result.get("total_node_count", 0),
                "completed_node_count": len(result.get("completed_nodes", [])),
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def get_run(
    flow_id: str,
    tenant_id: str,
    batch_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    return success_response(load_run_state(settings, flow_id, tenant_id, batch_id))


@router.get("/runs")
def list_runs(
    flow_id: str = "",
    status: str = "",
    limit: int = 20,
    offset: int = 0,
    settings: Annotated[WorkflowSettings, Depends(get_settings)] = None,
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)] = "",
) -> dict:
    tenant_id = _resolve_tenant_id(None, authenticated_tenant_id)
    database_url = require_database(settings)
    tenant = get_tenant_by_id(database_url, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    runs, total = list_workflow_runs(
        database_url,
        tenant_id=tenant_id,
        flow_id=flow_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    response = WorkflowRunListResponse(
        tenant_id=tenant_id,
        total=total,
        limit=max(1, min(int(limit), 200)),
        offset=max(0, int(offset)),
        runs=[_build_workflow_run_item(item) for item in runs],
    )
    return success_response(response.model_dump())


@router.get("/artifacts")
def get_artifacts(
    flow_id: str = "",
    limit: int = 20,
    offset: int = 0,
    settings: Annotated[WorkflowSettings, Depends(get_settings)] = None,
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)] = "",
) -> dict:
    tenant_id = _resolve_tenant_id(None, authenticated_tenant_id)
    database_url = require_database(settings)
    tenant = get_tenant_by_id(database_url, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    items, total = list_artifacts(
        database_url,
        tenant_id=tenant_id,
        flow_id=flow_id,
        limit=limit,
        offset=offset,
    )
    response = ArtifactListResponse(
        tenant_id=tenant_id,
        total=total,
        limit=max(1, min(int(limit), 200)),
        offset=max(0, int(offset)),
        items=[_build_artifact_item(item) for item in items],
    )
    return success_response(response.model_dump())


@router.get("/artifacts/{artifact_id}")
def get_artifact_detail(
    artifact_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(None, authenticated_tenant_id)
    database_url = require_database(settings)
    tenant = get_tenant_by_id(database_url, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    artifact = get_artifact(database_url, tenant_id=tenant_id, artifact_id=artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    return success_response(_build_artifact_item(artifact).model_dump())


@router.get("/schedules")
def get_schedules(
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return get_tenant_schedules(authenticated_tenant_id, settings, authenticated_tenant_id)


@router.get("/tables")
def list_tables(
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return list_tenant_tables(authenticated_tenant_id, settings, authenticated_tenant_id)


@router.get("/tables/{dataset_key}")
def get_table_rows(
    dataset_key: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
) -> dict:
    return get_tenant_table_rows(
        authenticated_tenant_id,
        dataset_key,
        settings,
        authenticated_tenant_id,
        limit=limit,
        offset=offset,
        order=order,
    )


@router.post("/tables/{dataset_key}")
def create_table_row(
    dataset_key: str,
    request: DatasetTableRowRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return create_tenant_table_row(authenticated_tenant_id, dataset_key, request, settings, authenticated_tenant_id)


@router.put("/tables/{dataset_key}/{record_id}")
def update_table_row(
    dataset_key: str,
    record_id: str,
    request: DatasetTableRowRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return update_tenant_table_row(authenticated_tenant_id, dataset_key, record_id, request, settings, authenticated_tenant_id)


@router.delete("/tables/{dataset_key}/{record_id}")
def delete_table_row(
    dataset_key: str,
    record_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return delete_tenant_table_row(authenticated_tenant_id, dataset_key, record_id, settings, authenticated_tenant_id)


@router.get("/schedules/{flow_id}")
def get_schedule(
    flow_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return get_tenant_schedule(authenticated_tenant_id, flow_id, settings, authenticated_tenant_id)


@router.put("/schedules/{flow_id}")
def put_schedule(
    flow_id: str,
    request: UpsertTenantFlowScheduleRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return put_tenant_schedule(authenticated_tenant_id, flow_id, request, settings, authenticated_tenant_id)


@router.delete("/schedules/{flow_id}")
def delete_schedule(
    flow_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return delete_tenant_schedule(authenticated_tenant_id, flow_id, settings, authenticated_tenant_id)


@router.post("/schedules/{flow_id}/trigger")
def trigger_schedule(
    flow_id: str,
    runtime: Annotated[GraphRuntime, Depends(get_runtime)],
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return trigger_tenant_schedule(authenticated_tenant_id, flow_id, runtime, settings, authenticated_tenant_id)


@router.post("/flows/{flow_id}/runs/{batch_id}/resume")
def resume_authenticated_flow(
    flow_id: str,
    batch_id: str,
    runtime: Annotated[GraphRuntime, Depends(get_runtime)],
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return resume_flow(flow_id, authenticated_tenant_id, batch_id, runtime, settings, authenticated_tenant_id)


@router.get("/flows/{flow_id}/runs/{batch_id}")
def get_authenticated_run(
    flow_id: str,
    batch_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return get_run(flow_id, authenticated_tenant_id, batch_id, settings, authenticated_tenant_id)
