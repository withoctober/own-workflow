from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request

from app.utils import read_json
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
