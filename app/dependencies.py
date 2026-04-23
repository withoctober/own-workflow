from __future__ import annotations

from pathlib import Path

from fastapi import Depends, Header, HTTPException, Request

from app.utils import read_json
from model import get_tenant_by_api_key
from workflow.runtime.engine import GraphRuntime
from workflow.settings import WorkflowSettings


def get_root(request: Request) -> Path:
    return request.app.state.root


def get_settings(request: Request) -> WorkflowSettings:
    return request.app.state.settings


def get_runtime(request: Request) -> GraphRuntime:
    return request.app.state.runtime


def load_run_state(settings: WorkflowSettings, flow_id: str, tenant_id: str, batch_id: str) -> dict:
    path = settings.run_dir / tenant_id / flow_id / batch_id / "state.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="run not found")
    return read_json(path)


async def require_tenant_api_key(
    request: Request,
    settings: WorkflowSettings = Depends(get_settings),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str:
    if not x_api_key or not x_api_key.strip():
        raise HTTPException(status_code=401, detail="缺少 X-API-Key")

    database_url = settings.database_url
    if not database_url.strip():
        raise HTTPException(status_code=400, detail="缺少 DATABASE_URL，当前未启用 PostgreSQL 配置")

    tenant = get_tenant_by_api_key(database_url, x_api_key)
    if tenant is None:
        raise HTTPException(status_code=401, detail="X-API-Key 无效")

    tenant_id = str(request.path_params.get("tenant_id") or "").strip()
    if not tenant_id:
        tenant_id = str(request.query_params.get("tenant_id") or "").strip()
    if not tenant_id:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            tenant_id = str(payload.get("tenant_id") or "").strip()

    if tenant_id and tenant_id != tenant.tenant_id:
        raise HTTPException(status_code=403, detail="X-API-Key 与 tenant_id 不匹配")
    return tenant.tenant_id
