from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


DEFAULT_FEISHU_API_BASE = "https://open.feishu.cn/open-apis"


@dataclass(slots=True)
class Tenant:
    id: str
    tenant_id: str
    tenant_name: str
    is_active: bool
    default_llm_model: str
    timeout_seconds: int
    max_retries: int


@dataclass(slots=True)
class TenantFeishuConfig:
    tenant_pk: str
    app_id: str
    app_secret: str
    tenant_access_token: str | None
    config: dict[str, Any]


def slugify_tenant_name(tenant_name: str) -> str:
    """Convert a tenant display name to a stable tenant_id prefix."""
    normalized = re.sub(r"[^a-z0-9]+", "-", tenant_name.strip().lower())
    normalized = normalized.strip("-")
    return normalized or "tenant"


def tenant_tables_sql() -> list[str]:
    return [
        """
        create table if not exists tenants (
          id uuid primary key default gen_random_uuid(),
          tenant_id text not null unique,
          tenant_name text not null,
          is_active boolean not null default true,
          default_llm_model text not null default '',
          timeout_seconds integer not null default 30,
          max_retries integer not null default 2,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        )
        """,
        """
        create table if not exists tenant_feishu_configs (
          tenant_pk uuid primary key references tenants(id) on delete cascade,
          app_id text not null default '',
          app_secret text not null default '',
          tenant_access_token text,
          config jsonb not null default '{}'::jsonb,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        )
        """,
    ]


def connect_postgres(database_url: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 psycopg 依赖，请先安装 PostgreSQL 驱动") from exc
    return psycopg.connect(database_url, row_factory=dict_row)


def ensure_postgres_tables(database_url: str) -> None:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            for statement in tenant_tables_sql():
                cursor.execute(statement)
            cursor.execute(
                """
                do $$
                begin
                  if exists (
                    select 1
                    from information_schema.columns
                    where table_name = 'tenants' and column_name = 'tenant_key'
                  ) and not exists (
                    select 1
                    from information_schema.columns
                    where table_name = 'tenants' and column_name = 'tenant_id'
                  ) then
                    alter table tenants rename column tenant_key to tenant_id;
                  end if;
                end $$;
                """
            )
            cursor.execute(
                """
                do $$
                begin
                  if exists (
                    select 1
                    from information_schema.columns
                    where table_name = 'tenant_feishu_configs' and column_name = 'tenant_id'
                  ) and not exists (
                    select 1
                    from information_schema.columns
                    where table_name = 'tenant_feishu_configs' and column_name = 'tenant_pk'
                  ) then
                    alter table tenant_feishu_configs rename column tenant_id to tenant_pk;
                  end if;
                end $$;
                """
            )
        connection.commit()


def postgres_enabled(database_url: str | None) -> bool:
    return bool(str(database_url or "").strip())


def get_tenant_by_id(database_url: str, tenant_id: str) -> Tenant | None:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select id, tenant_id, tenant_name, is_active, default_llm_model, timeout_seconds, max_retries
                from tenants
                where tenant_id = %s
                limit 1
                """,
                (tenant_id,),
            )
            row = cursor.fetchone()
    if not row:
        return None
    return Tenant(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        tenant_name=str(row["tenant_name"]),
        is_active=bool(row["is_active"]),
        default_llm_model=str(row.get("default_llm_model") or ""),
        timeout_seconds=int(row.get("timeout_seconds") or 30),
        max_retries=int(row.get("max_retries") or 2),
    )


def list_tenants(database_url: str) -> list[Tenant]:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select id, tenant_id, tenant_name, is_active, default_llm_model, timeout_seconds, max_retries
                from tenants
                order by tenant_id asc
                """
            )
            rows = cursor.fetchall()
    return [
        Tenant(
            id=str(row["id"]),
            tenant_id=str(row["tenant_id"]),
            tenant_name=str(row["tenant_name"]),
            is_active=bool(row["is_active"]),
            default_llm_model=str(row.get("default_llm_model") or ""),
            timeout_seconds=int(row.get("timeout_seconds") or 30),
            max_retries=int(row.get("max_retries") or 2),
        )
        for row in rows
    ]


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


def get_tenant_feishu_config(database_url: str, tenant_id: str) -> TenantFeishuConfig | None:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select
                  f.tenant_pk,
                  f.app_id,
                  f.app_secret,
                  f.tenant_access_token,
                  f.config
                from tenant_feishu_configs f
                inner join tenants t on t.id = f.tenant_pk
                where t.tenant_id = %s
                limit 1
                """,
                (tenant_id,),
            )
            row = cursor.fetchone()
    if not row:
        return None
    config = row.get("config")
    if not isinstance(config, dict):
        config = {}
    return TenantFeishuConfig(
        tenant_pk=str(row["tenant_pk"]),
        app_id=str(row.get("app_id") or ""),
        app_secret=str(row.get("app_secret") or ""),
        tenant_access_token=str(row.get("tenant_access_token") or "").strip() or None,
        config=config,
    )


def upsert_tenant(
    database_url: str,
    *,
    tenant_id: str,
    tenant_name: str,
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
                  is_active,
                  default_llm_model,
                  timeout_seconds,
                  max_retries
                )
                values (%s, %s, %s, %s, %s, %s)
                on conflict (tenant_id) do update set
                  tenant_name = excluded.tenant_name,
                  is_active = excluded.is_active,
                  default_llm_model = excluded.default_llm_model,
                  timeout_seconds = excluded.timeout_seconds,
                  max_retries = excluded.max_retries,
                  updated_at = now()
                returning id, tenant_id, tenant_name, is_active, default_llm_model, timeout_seconds, max_retries
                """,
                (
                    tenant_id,
                    tenant_name,
                    is_active,
                    default_llm_model,
                    timeout_seconds,
                    max_retries,
                ),
            )
            row = cursor.fetchone()
        connection.commit()
    assert row is not None
    return Tenant(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        tenant_name=str(row["tenant_name"]),
        is_active=bool(row["is_active"]),
        default_llm_model=str(row.get("default_llm_model") or ""),
        timeout_seconds=int(row.get("timeout_seconds") or 30),
        max_retries=int(row.get("max_retries") or 2),
    )


def upsert_tenant_feishu_config(
    database_url: str,
    *,
    tenant_pk: str,
    app_id: str,
    app_secret: str,
    tenant_access_token: str | None,
    config: dict[str, Any],
) -> None:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into tenant_feishu_configs (
                  tenant_pk,
                  app_id,
                  app_secret,
                  tenant_access_token,
                  config
                )
                values (%s, %s, %s, %s, %s::jsonb)
                on conflict (tenant_pk) do update set
                  app_id = excluded.app_id,
                  app_secret = excluded.app_secret,
                  tenant_access_token = excluded.tenant_access_token,
                  config = excluded.config,
                  updated_at = now()
                """,
                (
                    tenant_pk,
                    app_id,
                    app_secret,
                    tenant_access_token,
                    json.dumps(config, ensure_ascii=False),
                ),
            )
        connection.commit()


def get_feishu_runtime_config(database_url: str, tenant_id: str) -> dict[str, Any] | None:
    tenant = get_tenant_by_id(database_url, tenant_id)
    feishu = get_tenant_feishu_config(database_url, tenant_id)
    if tenant is None or feishu is None:
        return None
    payload = feishu.config if isinstance(feishu.config, dict) else {}
    return {
        "tenant_id": tenant.tenant_id,
        "app_id": feishu.app_id,
        "app_secret": feishu.app_secret,
        "tenant_access_token": feishu.tenant_access_token or "",
        "api_base": str(payload.get("api_base") or DEFAULT_FEISHU_API_BASE),
        "timeout_seconds": int(payload.get("timeout_seconds") or tenant.timeout_seconds or 30),
        "max_retries": int(payload.get("max_retries") or tenant.max_retries or 2),
        "user_id_type": str(payload.get("user_id_type") or "open_id"),
        "tables": payload.get("tables") if isinstance(payload.get("tables"), dict) else {},
        "docs": payload.get("docs") if isinstance(payload.get("docs"), dict) else {},
    }
