from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_runtime, get_settings, load_run_state
from app.model import (
    ensure_postgres_tables,
    generate_tenant_id,
    get_feishu_runtime_config,
    get_tenant_by_id,
    get_tenant_feishu_config,
    list_tenants,
    postgres_enabled,
    upsert_tenant,
    upsert_tenant_feishu_config,
)
from app.schemas import (
    CreateTenantRequest,
    RunFlowRequest,
    TenantFeishuConfigResponse,
    TenantResponse,
    UpsertTenantFeishuConfigRequest,
    UpsertTenantRequest,
    success_response,
)
from workflow.integrations.feishu import build_remote_feishu_config
from workflow.runtime.tenant import TenantRuntimeConfig
from workflow.runtime.engine import GraphRuntime, RunRequest
from workflow.settings import WorkflowSettings
from workflow.store import StoreError


router = APIRouter()


def require_database(settings: WorkflowSettings) -> str:
    if not postgres_enabled(settings.database_url):
        raise HTTPException(status_code=400, detail="缺少 DATABASE_URL，当前未启用 PostgreSQL 配置")
    ensure_postgres_tables(settings.database_url)
    return settings.database_url


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
        is_active=request.is_active,
        default_llm_model=request.default_llm_model,
        timeout_seconds=request.timeout_seconds,
        max_retries=request.max_retries,
    )
    return success_response(
        TenantResponse(
            tenant_id=tenant.tenant_id,
            tenant_name=tenant.tenant_name,
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
) -> dict:
    database_url = require_database(settings)
    tenant = upsert_tenant(
        database_url,
        tenant_id=tenant_id,
        tenant_name=request.tenant_name,
        is_active=request.is_active,
        default_llm_model=request.default_llm_model,
        timeout_seconds=request.timeout_seconds,
        max_retries=request.max_retries,
    )
    return success_response(
        TenantResponse(
            tenant_id=tenant.tenant_id,
            tenant_name=tenant.tenant_name,
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
) -> dict:
    database_url = require_database(settings)
    tenant = get_tenant_by_id(database_url, tenant_id)
    feishu = get_tenant_feishu_config(database_url, tenant_id)
    if tenant is None or feishu is None:
        raise HTTPException(status_code=404, detail="tenant feishu config not found")
    return success_response(
        TenantFeishuConfigResponse(
            tenant_id=tenant.tenant_id,
            tenant_name=tenant.tenant_name,
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


@router.put("/tenants/{tenant_id}/feishu")
def put_tenant_feishu(
    tenant_id: str,
    request: UpsertTenantFeishuConfigRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
) -> dict:
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
def list_flows(runtime: Annotated[GraphRuntime, Depends(get_runtime)]) -> dict:
    return success_response({"flows": runtime.list_flows()})


@router.post("/flows/{flow_id}/runs")
def run_flow(
    flow_id: str,
    request: RunFlowRequest,
    runtime: Annotated[GraphRuntime, Depends(get_runtime)],
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
) -> dict:
    try:
        database_url = require_database(settings)
        runtime_payload = get_feishu_runtime_config(database_url, request.tenant_id)
        if runtime_payload is None:
            raise HTTPException(status_code=400, detail=f"PostgreSQL 中未找到 tenant_id={request.tenant_id} 的飞书配置")
        result = runtime.run(
            RunRequest(
                flow_id=flow_id,
                tenant_id=request.tenant_id,
                batch_id=request.batch_id,
                source_url=request.source_url,
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


@router.get("/flows/{flow_id}/runs/{tenant_id}/{batch_id}")
def get_run(
    flow_id: str,
    tenant_id: str,
    batch_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
) -> dict:
    return success_response(load_run_state(settings, flow_id, tenant_id, batch_id))
