from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any


DEFAULT_FEISHU_API_BASE = "https://open.feishu.cn/open-apis"


@dataclass(slots=True)
class Tenant:
    id: str
    tenant_id: str
    tenant_name: str
    api_key: str
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


@dataclass(slots=True)
class TenantFlowSchedule:
    id: str
    tenant_pk: str
    tenant_id: str
    flow_id: str
    cron_expr: str
    is_active: bool
    request_payload: dict[str, Any]
    batch_id_prefix: str
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_status: str
    last_error: str
    last_batch_id: str
    is_running: bool
    locked_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None


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
          api_key text not null default '',
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
        """
        create table if not exists tenant_flow_schedules (
          id uuid primary key default gen_random_uuid(),
          tenant_pk uuid not null references tenants(id) on delete cascade,
          flow_id text not null,
          cron_expr text not null,
          is_active boolean not null default true,
          request_payload jsonb not null default '{}'::jsonb,
          batch_id_prefix text not null default '',
          next_run_at timestamptz,
          last_run_at timestamptz,
          last_status text not null default '',
          last_error text not null default '',
          last_batch_id text not null default '',
          is_running boolean not null default false,
          locked_at timestamptz,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          unique (tenant_pk, flow_id)
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
                  if not exists (
                    select 1
                    from information_schema.columns
                    where table_name = 'tenants' and column_name = 'api_key'
                  ) then
                    alter table tenants add column api_key text not null default '';
                  end if;
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
    return [
        Tenant(
            id=str(row["id"]),
            tenant_id=str(row["tenant_id"]),
            tenant_name=str(row["tenant_name"]),
            api_key=str(row.get("api_key") or ""),
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


def _build_schedule(row: dict[str, Any]) -> TenantFlowSchedule:
    payload = row.get("request_payload")
    if not isinstance(payload, dict):
        payload = {}
    return TenantFlowSchedule(
        id=str(row["id"]),
        tenant_pk=str(row["tenant_pk"]),
        tenant_id=str(row["tenant_id"]),
        flow_id=str(row["flow_id"]),
        cron_expr=str(row["cron_expr"]),
        is_active=bool(row["is_active"]),
        request_payload=payload,
        batch_id_prefix=str(row.get("batch_id_prefix") or ""),
        next_run_at=row.get("next_run_at"),
        last_run_at=row.get("last_run_at"),
        last_status=str(row.get("last_status") or ""),
        last_error=str(row.get("last_error") or ""),
        last_batch_id=str(row.get("last_batch_id") or ""),
        is_running=bool(row.get("is_running") or False),
        locked_at=row.get("locked_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def get_tenant_flow_schedule(database_url: str, tenant_id: str, flow_id: str) -> TenantFlowSchedule | None:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select
                  s.id,
                  s.tenant_pk,
                  t.tenant_id,
                  s.flow_id,
                  s.cron_expr,
                  s.is_active,
                  s.request_payload,
                  s.batch_id_prefix,
                  s.next_run_at,
                  s.last_run_at,
                  s.last_status,
                  s.last_error,
                  s.last_batch_id,
                  s.is_running,
                  s.locked_at,
                  s.created_at,
                  s.updated_at
                from tenant_flow_schedules s
                inner join tenants t on t.id = s.tenant_pk
                where t.tenant_id = %s and s.flow_id = %s
                limit 1
                """,
                (tenant_id, flow_id),
            )
            row = cursor.fetchone()
    if not row:
        return None
    return _build_schedule(row)


def list_tenant_flow_schedules(database_url: str, tenant_id: str) -> list[TenantFlowSchedule]:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select
                  s.id,
                  s.tenant_pk,
                  t.tenant_id,
                  s.flow_id,
                  s.cron_expr,
                  s.is_active,
                  s.request_payload,
                  s.batch_id_prefix,
                  s.next_run_at,
                  s.last_run_at,
                  s.last_status,
                  s.last_error,
                  s.last_batch_id,
                  s.is_running,
                  s.locked_at,
                  s.created_at,
                  s.updated_at
                from tenant_flow_schedules s
                inner join tenants t on t.id = s.tenant_pk
                where t.tenant_id = %s
                order by s.flow_id asc
                """,
                (tenant_id,),
            )
            rows = cursor.fetchall()
    return [_build_schedule(row) for row in rows]


def upsert_tenant_flow_schedule(
    database_url: str,
    *,
    tenant_pk: str,
    tenant_id: str,
    flow_id: str,
    cron_expr: str,
    is_active: bool,
    request_payload: dict[str, Any],
    batch_id_prefix: str,
    next_run_at: datetime | None,
) -> TenantFlowSchedule:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into tenant_flow_schedules (
                  tenant_pk,
                  flow_id,
                  cron_expr,
                  is_active,
                  request_payload,
                  batch_id_prefix,
                  next_run_at
                )
                values (%s, %s, %s, %s, %s::jsonb, %s, %s)
                on conflict (tenant_pk, flow_id) do update set
                  cron_expr = excluded.cron_expr,
                  is_active = excluded.is_active,
                  request_payload = excluded.request_payload,
                  batch_id_prefix = excluded.batch_id_prefix,
                  next_run_at = excluded.next_run_at,
                  is_running = false,
                  locked_at = null,
                  updated_at = now()
                returning
                  id,
                  tenant_pk,
                  flow_id,
                  cron_expr,
                  is_active,
                  request_payload,
                  batch_id_prefix,
                  next_run_at,
                  last_run_at,
                  last_status,
                  last_error,
                  last_batch_id,
                  is_running,
                  locked_at,
                  created_at,
                  updated_at
                """,
                (
                    tenant_pk,
                    flow_id,
                    cron_expr,
                    is_active,
                    json.dumps(request_payload, ensure_ascii=False),
                    batch_id_prefix,
                    next_run_at,
                ),
            )
            row = cursor.fetchone()
        connection.commit()
    assert row is not None
    schedule_row = dict(row)
    schedule_row["tenant_id"] = tenant_id
    return _build_schedule(schedule_row)


def delete_tenant_flow_schedule(database_url: str, tenant_id: str, flow_id: str) -> bool:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                delete from tenant_flow_schedules s
                using tenants t
                where s.tenant_pk = t.id
                  and t.tenant_id = %s
                  and s.flow_id = %s
                """,
                (tenant_id, flow_id),
            )
            deleted = cursor.rowcount > 0
        connection.commit()
    return deleted


def list_due_tenant_flow_schedules(
    database_url: str,
    *,
    run_at: datetime,
    limit: int = 20,
) -> list[TenantFlowSchedule]:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select
                  s.id,
                  s.tenant_pk,
                  t.tenant_id,
                  s.flow_id,
                  s.cron_expr,
                  s.is_active,
                  s.request_payload,
                  s.batch_id_prefix,
                  s.next_run_at,
                  s.last_run_at,
                  s.last_status,
                  s.last_error,
                  s.last_batch_id,
                  s.is_running,
                  s.locked_at,
                  s.created_at,
                  s.updated_at
                from tenant_flow_schedules s
                inner join tenants t on t.id = s.tenant_pk
                where s.is_active = true
                  and s.is_running = false
                  and s.next_run_at is not null
                  and s.next_run_at <= %s
                order by s.next_run_at asc, s.created_at asc
                limit %s
                """,
                (run_at, limit),
            )
            rows = cursor.fetchall()
    return [_build_schedule(row) for row in rows]


def claim_tenant_flow_schedule(database_url: str, *, schedule_id: str, run_at: datetime) -> TenantFlowSchedule | None:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                with claimed as (
                  update tenant_flow_schedules
                  set is_running = true,
                      locked_at = %s,
                      updated_at = now()
                  where id = %s
                    and is_active = true
                    and is_running = false
                    and next_run_at is not null
                    and next_run_at <= %s
                  returning *
                )
                select
                  c.id,
                  c.tenant_pk,
                  t.tenant_id,
                  c.flow_id,
                  c.cron_expr,
                  c.is_active,
                  c.request_payload,
                  c.batch_id_prefix,
                  c.next_run_at,
                  c.last_run_at,
                  c.last_status,
                  c.last_error,
                  c.last_batch_id,
                  c.is_running,
                  c.locked_at,
                  c.created_at,
                  c.updated_at
                from claimed c
                inner join tenants t on t.id = c.tenant_pk
                """,
                (run_at, schedule_id, run_at),
            )
            row = cursor.fetchone()
        connection.commit()
    if not row:
        return None
    return _build_schedule(row)


def complete_tenant_flow_schedule_run(
    database_url: str,
    *,
    schedule_id: str,
    next_run_at: datetime | None,
    last_run_at: datetime,
    last_status: str,
    last_error: str,
    last_batch_id: str,
) -> None:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update tenant_flow_schedules
                set is_running = false,
                    locked_at = null,
                    next_run_at = %s,
                    last_run_at = %s,
                    last_status = %s,
                    last_error = %s,
                    last_batch_id = %s,
                    updated_at = now()
                where id = %s
                """,
                (
                    next_run_at,
                    last_run_at,
                    last_status,
                    last_error,
                    last_batch_id,
                    schedule_id,
                ),
            )
        connection.commit()


def reset_stale_tenant_flow_schedule_locks(
    database_url: str,
    *,
    stale_before: datetime,
) -> int:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update tenant_flow_schedules
                set is_running = false,
                    locked_at = null,
                    updated_at = now()
                where is_running = true
                  and locked_at is not null
                  and locked_at < %s
                """,
                (stale_before,),
            )
            count = cursor.rowcount
        connection.commit()
    return count


def list_active_schedules_without_next_run(database_url: str) -> list[TenantFlowSchedule]:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select
                  s.id,
                  s.tenant_pk,
                  t.tenant_id,
                  s.flow_id,
                  s.cron_expr,
                  s.is_active,
                  s.request_payload,
                  s.batch_id_prefix,
                  s.next_run_at,
                  s.last_run_at,
                  s.last_status,
                  s.last_error,
                  s.last_batch_id,
                  s.is_running,
                  s.locked_at,
                  s.created_at,
                  s.updated_at
                from tenant_flow_schedules s
                inner join tenants t on t.id = s.tenant_pk
                where s.is_active = true
                  and s.next_run_at is null
                order by s.created_at asc
                """
            )
            rows = cursor.fetchall()
    return [_build_schedule(row) for row in rows]


def update_tenant_flow_schedule_next_run(database_url: str, *, schedule_id: str, next_run_at: datetime | None) -> None:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update tenant_flow_schedules
                set next_run_at = %s,
                    updated_at = now()
                where id = %s
                """,
                (next_run_at, schedule_id),
            )
        connection.commit()
