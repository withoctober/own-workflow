from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_runtime, get_settings, load_run_state, require_tenant_api_key
from app.model import (
    delete_tenant_flow_schedule,
    ensure_postgres_tables,
    generate_tenant_id,
    get_tenant_flow_schedule,
    get_feishu_runtime_config,
    get_tenant_by_id,
    get_tenant_feishu_config,
    list_tenant_flow_schedules,
    list_tenants,
    postgres_enabled,
    upsert_tenant_flow_schedule,
    upsert_tenant,
    upsert_tenant_feishu_config,
)
from app.schemas import (
    CreateTenantRequest,
    RunFlowRequest,
    TenantFlowScheduleListResponse,
    TenantFlowScheduleResponse,
    TenantFeishuConfigResponse,
    TenantResponse,
    UpsertTenantFlowScheduleRequest,
    UpsertTenantFeishuConfigRequest,
    UpsertTenantRequest,
    success_response,
)
from workflow.flow.registry import has_flow_definition
from workflow.integrations.feishu import build_remote_feishu_config
from workflow.runtime.tenant import TenantRuntimeConfig
from workflow.runtime.engine import GraphRuntime, RunRequest
from workflow.runtime.scheduler import compute_next_run_at, normalize_batch_id_prefix, validate_cron_expression
from workflow.settings import WorkflowSettings
from workflow.store import StoreError


router = APIRouter()


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
    ensure_postgres_tables(settings.database_url)
    return settings.database_url


def _resolve_tenant_id(explicit_tenant_id: str | None, authenticated_tenant_id: str) -> str:
    tenant_id = str(explicit_tenant_id or "").strip()
    return tenant_id or authenticated_tenant_id


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
            timeout_seconds=tenant.timeout_seconds,
            max_retries=tenant.max_retries,
        ).model_dump()
    )


@router.put("/tenants/{tenant_id}")
def put_tenant(
    tenant_id: str,
    request: UpsertTenantRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    database_url = require_database(settings)
    tenant = upsert_tenant(
        database_url,
        tenant_id=tenant_id,
        tenant_name=request.tenant_name,
        api_key=request.api_key,
        is_active=request.is_active,
        default_llm_model=request.default_llm_model,
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
            timeout_seconds=tenant.timeout_seconds,
            max_retries=tenant.max_retries,
        ).model_dump()
    )


@router.get("/tenants/{tenant_id}/feishu")
def get_tenant_feishu(
    tenant_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    database_url = require_database(settings)
    tenant = get_tenant_by_id(database_url, tenant_id)
    feishu = get_tenant_feishu_config(database_url, tenant_id)
    if tenant is None or feishu is None:
        raise HTTPException(status_code=404, detail="tenant feishu config not found")
    return success_response(
        TenantFeishuConfigResponse(
            tenant_id=tenant.tenant_id,
            tenant_name=tenant.tenant_name,
            api_key=tenant.api_key,
            is_active=tenant.is_active,
            default_llm_model=tenant.default_llm_model,
            timeout_seconds=tenant.timeout_seconds,
            max_retries=tenant.max_retries,
            app_id=feishu.app_id,
            app_secret=feishu.app_secret,
            tenant_access_token=feishu.tenant_access_token or "",
            config=feishu.config,
        ).model_dump()
    )


@router.get("/tenants/{tenant_id}/schedules")
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


@router.get("/tenants/{tenant_id}/schedules/{flow_id}")
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


@router.put("/tenants/{tenant_id}/schedules/{flow_id}")
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
    schedule = upsert_tenant_flow_schedule(
        database_url,
        tenant_pk=tenant.id,
        tenant_id=tenant_id,
        flow_id=flow_id,
        cron_expr=request.cron,
        is_active=request.is_active,
        request_payload=request.request_payload.model_dump(),
        batch_id_prefix=normalize_batch_id_prefix(request.batch_id_prefix),
        next_run_at=next_run_at,
    )
    return success_response(build_schedule_response(schedule).model_dump())


@router.delete("/tenants/{tenant_id}/schedules/{flow_id}")
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


@router.post("/tenants/{tenant_id}/schedules/{flow_id}/trigger")
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
        runtime_payload = get_feishu_runtime_config(database_url, tenant_id)
        if runtime_payload is None:
            raise HTTPException(status_code=400, detail=f"PostgreSQL 中未找到 tenant_id={tenant_id} 的飞书配置")
        request_payload = schedule.request_payload if isinstance(schedule.request_payload, dict) else {}
        result = runtime.run(
            RunRequest(
                flow_id=flow_id,
                tenant_id=tenant_id,
                source_url=str(request_payload.get("source_url") or ""),
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


@router.put("/tenants/{tenant_id}/feishu")
def put_tenant_feishu(
    tenant_id: str,
    request: UpsertTenantFeishuConfigRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    database_url = require_database(settings)
    tenant = get_tenant_by_id(database_url, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")

    try:
        config_payload = build_remote_feishu_config(
            settings.root,
            app_id=request.app_id,
            app_secret=request.app_secret,
            tenant_access_token=request.tenant_access_token or None,
            table_url=request.base_url,
            document_urls={
                "行业报告": request.industry_report_url,
                "营销策划方案": request.marketing_plan_url,
                "关键词矩阵": request.keyword_matrix_url,
            },
            timeout_seconds=request.timeout_seconds,
            max_retries=request.max_retries,
        )
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    tenant = upsert_tenant(
        database_url,
        tenant_id=tenant_id,
        tenant_name=request.tenant_name,
        api_key=tenant.api_key,
        is_active=True,
        default_llm_model=request.default_llm_model,
        timeout_seconds=request.timeout_seconds,
        max_retries=request.max_retries,
    )

    upsert_tenant_feishu_config(
        database_url,
        tenant_pk=tenant.id,
        app_id=request.app_id,
        app_secret=request.app_secret,
        tenant_access_token=request.tenant_access_token or None,
        config=config_payload,
    )

    feishu = get_tenant_feishu_config(database_url, tenant_id)
    assert feishu is not None
    return success_response(
        TenantFeishuConfigResponse(
            tenant_id=tenant.tenant_id,
            tenant_name=tenant.tenant_name,
            api_key=tenant.api_key,
            is_active=tenant.is_active,
            default_llm_model=tenant.default_llm_model,
            timeout_seconds=tenant.timeout_seconds,
            max_retries=tenant.max_retries,
            app_id=feishu.app_id,
            app_secret=feishu.app_secret,
            tenant_access_token=feishu.tenant_access_token or "",
            config=feishu.config,
        ).model_dump()
    )


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
        runtime_payload = get_feishu_runtime_config(database_url, tenant_id)
        if runtime_payload is None:
            raise HTTPException(status_code=400, detail=f"PostgreSQL 中未找到 tenant_id={tenant_id} 的飞书配置")
        result = runtime.enqueue(
            RunRequest(
                flow_id=flow_id,
                tenant_id=tenant_id,
                batch_id=request.batch_id,
                source_url=request.source_url,
                tenant_runtime_config=TenantRuntimeConfig(payload=runtime_payload),
            )
        )
        return success_response(
            {
                "status": result["status"],
                "tenant_id": tenant_id,
                "flow_id": flow_id,
                "batch_id": result["batch_id"],
                "run_path": f"/flows/{flow_id}/runs/{result['batch_id']}",
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/flows/{flow_id}/runs/{tenant_id}/{batch_id}/resume")
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
        runtime_payload = get_feishu_runtime_config(database_url, tenant_id)
        if runtime_payload is None:
            raise HTTPException(status_code=400, detail=f"PostgreSQL 中未找到 tenant_id={tenant_id} 的飞书配置")
        state = load_run_state(settings, flow_id, tenant_id, batch_id)
        result = runtime.resume(
            RunRequest(
                flow_id=flow_id,
                tenant_id=tenant_id,
                batch_id=batch_id,
                source_url=str(state.get("source_url") or ""),
                tenant_runtime_config=TenantRuntimeConfig(payload=runtime_payload),
            )
        )
        return success_response(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/flows/{flow_id}/runs/{tenant_id}/{batch_id}")
def get_run(
    flow_id: str,
    tenant_id: str,
    batch_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    return success_response(load_run_state(settings, flow_id, tenant_id, batch_id))


@router.get("/tenant/feishu")
def get_authenticated_tenant_feishu(
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return get_tenant_feishu(authenticated_tenant_id, settings, authenticated_tenant_id)


@router.put("/tenant/feishu")
def put_authenticated_tenant_feishu(
    request: UpsertTenantFeishuConfigRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return put_tenant_feishu(authenticated_tenant_id, request, settings, authenticated_tenant_id)


@router.get("/tenant/schedules")
def get_authenticated_tenant_schedules(
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return get_tenant_schedules(authenticated_tenant_id, settings, authenticated_tenant_id)


@router.get("/tenant/schedules/{flow_id}")
def get_authenticated_tenant_schedule(
    flow_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return get_tenant_schedule(authenticated_tenant_id, flow_id, settings, authenticated_tenant_id)


@router.put("/tenant/schedules/{flow_id}")
def put_authenticated_tenant_schedule(
    flow_id: str,
    request: UpsertTenantFlowScheduleRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return put_tenant_schedule(authenticated_tenant_id, flow_id, request, settings, authenticated_tenant_id)


@router.delete("/tenant/schedules/{flow_id}")
def delete_authenticated_tenant_schedule(
    flow_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return delete_tenant_schedule(authenticated_tenant_id, flow_id, settings, authenticated_tenant_id)


@router.post("/tenant/schedules/{flow_id}/trigger")
def trigger_authenticated_tenant_schedule(
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
