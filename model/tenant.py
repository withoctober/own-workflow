from __future__ import annotations

import re
from typing import Any

from model.db import connect_postgres
from model.types import Tenant


def slugify_tenant_name(tenant_name: str) -> str:
    """Convert a tenant display name to a stable tenant_id prefix."""
    normalized = re.sub(r"[^a-z0-9]+", "-", tenant_name.strip().lower())
    normalized = normalized.strip("-")
    return normalized or "tenant"


def _build_tenant(row: dict[str, Any]) -> Tenant:
    return Tenant(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        tenant_name=str(row["tenant_name"]),
        api_key=str(row.get("api_key") or ""),
        is_active=bool(row["is_active"]),
        default_llm_model=str(row.get("default_llm_model") or ""),
        timeout_seconds=int(row.get("timeout_seconds") or 30),
        max_retries=int(row.get("max_retries") or 2),
    )


def get_tenant_by_id(database_url: str, tenant_id: str) -> Tenant | None:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select id, tenant_id, tenant_name, api_key, is_active, default_llm_model, timeout_seconds, max_retries
                from tenants
                where tenant_id = %s
                limit 1
                """,
                (tenant_id,),
            )
            row = cursor.fetchone()
    if not row:
        return None
    return _build_tenant(row)


def list_tenants(database_url: str) -> list[Tenant]:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select id, tenant_id, tenant_name, api_key, is_active, default_llm_model, timeout_seconds, max_retries
                from tenants
                order by tenant_id asc
                """
            )
            rows = cursor.fetchall()
    return [_build_tenant(row) for row in rows]


def get_tenant_by_api_key(database_url: str, api_key: str) -> Tenant | None:
    normalized_api_key = str(api_key).strip()
    if not normalized_api_key:
        return None
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select id, tenant_id, tenant_name, api_key, is_active, default_llm_model, timeout_seconds, max_retries
                from tenants
                where api_key = %s
                limit 1
                """,
                (normalized_api_key,),
            )
            row = cursor.fetchone()
    if not row:
        return None
    return _build_tenant(row)


def list_tenant_ids(database_url: str, prefix: str) -> list[str]:
    """Return existing tenant_ids that share the given prefix."""
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select tenant_id
                from tenants
                where tenant_id = %s or tenant_id like %s
                order by tenant_id asc
                """,
                (prefix, f"{prefix}-%"),
            )
            rows = cursor.fetchall()
    return [str(row["tenant_id"]) for row in rows]


def generate_tenant_id(database_url: str, tenant_name: str) -> str:
    """Generate a unique tenant_id from a tenant display name."""
    base = slugify_tenant_name(tenant_name)
    existing = set(list_tenant_ids(database_url, base))
    if base not in existing:
        return base
    suffix = 2
    while f"{base}-{suffix}" in existing:
        suffix += 1
    return f"{base}-{suffix}"


def upsert_tenant(
    database_url: str,
    *,
    tenant_id: str,
    tenant_name: str,
    api_key: str,
    is_active: bool = True,
    default_llm_model: str = "",
    timeout_seconds: int = 30,
    max_retries: int = 2,
) -> Tenant:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into tenants (
                  tenant_id,
                  tenant_name,
                  api_key,
                  is_active,
                  default_llm_model,
                  timeout_seconds,
                  max_retries
                )
                values (%s, %s, %s, %s, %s, %s, %s)
                on conflict (tenant_id) do update set
                  tenant_name = excluded.tenant_name,
                  api_key = excluded.api_key,
                  is_active = excluded.is_active,
                  default_llm_model = excluded.default_llm_model,
                  timeout_seconds = excluded.timeout_seconds,
                  max_retries = excluded.max_retries,
                  updated_at = now()
                returning id, tenant_id, tenant_name, api_key, is_active, default_llm_model, timeout_seconds, max_retries
                """,
                (
                    tenant_id,
                    tenant_name,
                    api_key,
                    is_active,
                    default_llm_model,
                    timeout_seconds,
                    max_retries,
                ),
            )
            row = cursor.fetchone()
        connection.commit()
    assert row is not None
    return _build_tenant(row)


def validate_tenant_api_key(database_url: str, tenant_id: str, api_key: str) -> bool:
    normalized_tenant_id = str(tenant_id).strip()
    normalized_api_key = str(api_key).strip()
    if not normalized_tenant_id or not normalized_api_key:
        return False
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select 1
                from tenants
                where tenant_id = %s and api_key = %s
                limit 1
                """,
                (normalized_tenant_id, normalized_api_key),
            )
            row = cursor.fetchone()
    return row is not None


def get_tenant_runtime_config(database_url: str, tenant_id: str) -> dict[str, Any] | None:
    tenant = get_tenant_by_id(database_url, tenant_id)
    if tenant is None:
        return None
    return {
        "tenant_id": tenant.tenant_id,
        "database_url": database_url,
        "store_type": "database",
        "timeout_seconds": int(tenant.timeout_seconds or 30),
        "max_retries": int(tenant.max_retries or 2),
        "tables": {},
        "docs": {},
    }
