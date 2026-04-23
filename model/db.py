from __future__ import annotations


def tenant_tables_sql() -> list[str]:
    return [
        """
        create extension if not exists pgcrypto
        """,
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
        """
        create table if not exists store_entries (
          id uuid primary key default gen_random_uuid(),
          tenant_id text not null,
          dataset_key text not null,
          entry_type text not null,
          record_key text not null default '',
          title text not null default '',
          batch_id text not null default '',
          sort_order integer not null default 0,
          content_text text not null default '',
          payload jsonb not null default '{}'::jsonb,
          schema_version integer not null default 1,
          source_ref text not null default '',
          is_deleted boolean not null default false,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          check (entry_type in ('row', 'doc'))
        )
        """,
        """
        create unique index if not exists ux_store_entries_active
        on store_entries (tenant_id, dataset_key, entry_type, record_key)
        where is_deleted = false
        """,
        """
        create index if not exists ix_store_entries_dataset
        on store_entries (tenant_id, dataset_key, entry_type, updated_at desc)
        where is_deleted = false
        """,
        """
        create index if not exists ix_store_entries_batch
        on store_entries (tenant_id, batch_id, dataset_key)
        where is_deleted = false
        """,
        """
        create index if not exists ix_store_entries_payload_gin
        on store_entries using gin (payload jsonb_path_ops)
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
        connection.commit()


def postgres_enabled(database_url: str | None) -> bool:
    return bool(str(database_url or "").strip())
