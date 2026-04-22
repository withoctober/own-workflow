from __future__ import annotations

from pathlib import Path

from workflow.store.base import Store, StoreError
from workflow.store.feishu import FeishuResourceConfig, FeishuStore
from workflow.runtime.tenant import TenantRuntimeConfig


def build_store(
    root: Path,
    *,
    tenant_config: TenantRuntimeConfig | None,
) -> Store:
    config = load_feishu_config(root, tenant_config=tenant_config)
    return FeishuStore(root, config)


def load_feishu_config(
    root: Path,
    tenant_config: TenantRuntimeConfig | None,
) -> FeishuResourceConfig:
    if tenant_config is None:
        raise StoreError("缺少租户运行配置，请在 app 层解析后注入 workflow 上下文")
    return FeishuResourceConfig(
        path=tenant_config.feishu_resource_path(root),
        payload=tenant_config.payload,
    )
