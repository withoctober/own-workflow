from __future__ import annotations

from pathlib import Path

from workflow.store.database import DatabaseStore
from workflow.store.base import Store, StoreError
from workflow.runtime.tenant import TenantRuntimeConfig


def build_store(
    root: Path,
    *,
    tenant_config: TenantRuntimeConfig | None,
) -> Store:
    if tenant_config is None:
        raise StoreError("缺少租户运行配置，请在 app 层解析后注入 workflow 上下文")
    return DatabaseStore(tenant_config)
