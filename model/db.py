from __future__ import annotations

from contextlib import contextmanager
from queue import Empty, Full, LifoQueue
from threading import Lock


_POSTGRES_POOL_LOCK = Lock()
_POSTGRES_POOL_MAX_SIZE = 8
_POSTGRES_POOLS: dict[str, LifoQueue] = {}


def _get_postgres_pool(database_url: str) -> LifoQueue:
    with _POSTGRES_POOL_LOCK:
        pool = _POSTGRES_POOLS.get(database_url)
        if pool is None:
            pool = LifoQueue(maxsize=_POSTGRES_POOL_MAX_SIZE)
            _POSTGRES_POOLS[database_url] = pool
        return pool


def _close_postgres_connection(connection) -> None:
    try:
        connection.close()
    except Exception:
        pass


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
          api_mode text not null default 'system',
          api_ref jsonb not null default '{}'::jsonb,
          timeout_seconds integer not null default 600,
          max_retries integer not null default 2,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        )
        """,
        """
        create unique index if not exists ux_tenants_api_key
        on tenants (api_key)
        where api_key <> ''
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
        """
        create table if not exists workflow_runs (
          id uuid primary key default gen_random_uuid(),
          tenant_id text not null,
          flow_id text not null,
          batch_id text not null,
          trigger_mode text not null default '',
          source_url text not null default '',
          status text not null default '',
          current_node text not null default '',
          current_node_index integer not null default 0,
          total_node_count integer not null default 0,
          resume_count integer not null default 0,
          completed_node_count integer not null default 0,
          error_count integer not null default 0,
          last_message text not null default '',
          last_error text not null default '',
          started_at timestamptz,
          finished_at timestamptz,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          unique (tenant_id, flow_id, batch_id)
        )
        """,
        """
        create index if not exists ix_workflow_runs_tenant_updated
        on workflow_runs (tenant_id, updated_at desc)
        """,
        """
        create index if not exists ix_workflow_runs_tenant_flow_updated
        on workflow_runs (tenant_id, flow_id, updated_at desc)
        """,
        """
        create index if not exists ix_workflow_runs_tenant_status_updated
        on workflow_runs (tenant_id, status, updated_at desc)
        """,
        """
        create table if not exists artifacts (
          id uuid primary key default gen_random_uuid(),
          tenant_id text not null,
          flow_id text not null,
          batch_id text not null,
          workflow_run_id text not null default '',
          artifact_type text not null default 'content',
          title text not null default '',
          content text not null default '',
          tags text not null default '',
          cover_prompt text not null default '',
          cover_url text not null default '',
          image_prompts jsonb not null default '[]'::jsonb,
          image_urls jsonb not null default '[]'::jsonb,
          source_url text not null default '',
          payload jsonb not null default '{}'::jsonb,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          unique (tenant_id, flow_id, batch_id, artifact_type)
        )
        """,
        """
        create index if not exists ix_artifacts_tenant_updated
        on artifacts (tenant_id, updated_at desc)
        """,
        """
        create index if not exists ix_artifacts_tenant_flow_updated
        on artifacts (tenant_id, flow_id, updated_at desc)
        """,
        """
        create index if not exists ix_artifacts_batch
        on artifacts (tenant_id, batch_id)
        """,
        """
        create table if not exists wallet_ledger_entries (
          id uuid primary key default gen_random_uuid(),
          tenant_id text not null,
          entry_type text not null,
          amount numeric(18,4) not null default 0,
          title text not null default '',
          channel text not null default '',
          provider text not null default '',
          provider_event_id text not null default '',
          related_resource_type text not null default '',
          related_resource_id text not null default '',
          status text not null default 'completed',
          detail text not null default '',
          metadata jsonb not null default '{}'::jsonb,
          occurred_at timestamptz not null default now(),
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        )
        """,
        """
        create index if not exists ix_wallet_ledger_entries_tenant_occurred
        on wallet_ledger_entries (tenant_id, occurred_at desc, created_at desc)
        """,
        """
        create index if not exists ix_wallet_ledger_entries_tenant_type_occurred
        on wallet_ledger_entries (tenant_id, entry_type, occurred_at desc, created_at desc)
        """,
        """
        create unique index if not exists ux_wallet_ledger_entries_provider_event
        on wallet_ledger_entries (tenant_id, provider, provider_event_id)
        where provider <> '' and provider_event_id <> ''
        """,
        """
        create table if not exists tenant_wallets (
          id uuid primary key default gen_random_uuid(),
          tenant_id text not null unique,
          available_balance numeric(18,4) not null default 0,
          total_recharged numeric(18,4) not null default 0,
          total_consumed numeric(18,4) not null default 0,
          currency text not null default 'CNY',
          last_recharge_at timestamptz,
          last_consume_at timestamptz,
          last_synced_at timestamptz,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        )
        """,
        """
        create index if not exists ix_tenant_wallets_balance
        on tenant_wallets (available_balance desc, updated_at desc)
        """,
        """
        create table if not exists provider_usage_events (
          id uuid primary key default gen_random_uuid(),
          tenant_id text not null,
          provider text not null default '',
          provider_event_id text not null default '',
          request_id text not null default '',
          channel text not null default '',
          feature_key text not null default '',
          model_name text not null default '',
          tokens_in integer not null default 0,
          tokens_out integer not null default 0,
          image_count integer not null default 0,
          amount numeric(18,4) not null default 0,
          currency text not null default 'CNY',
          related_resource_type text not null default '',
          related_resource_id text not null default '',
          ledger_entry_id uuid references wallet_ledger_entries(id) on delete set null,
          status text not null default 'completed',
          payload jsonb not null default '{}'::jsonb,
          occurred_at timestamptz not null default now(),
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        )
        """,
        """
        create unique index if not exists ux_provider_usage_events_provider_event
        on provider_usage_events (tenant_id, provider, provider_event_id)
        where provider <> '' and provider_event_id <> ''
        """,
        """
        create index if not exists ix_provider_usage_events_tenant_occurred
        on provider_usage_events (tenant_id, occurred_at desc, created_at desc)
        """,
        """
        create index if not exists ix_provider_usage_events_tenant_channel
        on provider_usage_events (tenant_id, channel, occurred_at desc)
        """,
    ]


def deprecated_tables_sql() -> list[str]:
    return [
        """
        drop table if exists tenant_feishu_configs
        """,
    ]


@contextmanager
def connect_postgres(database_url: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 psycopg 依赖，请先安装 PostgreSQL 驱动") from exc

    pool = _get_postgres_pool(database_url)
    try:
        connection = pool.get_nowait()
    except Empty:
        connection = psycopg.connect(database_url, row_factory=dict_row)
    else:
        if getattr(connection, "closed", False) or getattr(connection, "broken", False):
            _close_postgres_connection(connection)
            connection = psycopg.connect(database_url, row_factory=dict_row)

    try:
        yield connection
        if not getattr(connection, "closed", False):
            connection.commit()
    except Exception:
        if not getattr(connection, "closed", False):
            try:
                connection.rollback()
            except Exception:
                _close_postgres_connection(connection)
        raise
    finally:
        if getattr(connection, "closed", False) or getattr(connection, "broken", False):
            _close_postgres_connection(connection)
            return
        try:
            pool.put_nowait(connection)
        except Full:
            _close_postgres_connection(connection)


_ENSURED_DATABASES: set[str] = set()


def ensure_postgres_tables(database_url: str) -> None:
    if database_url in _ENSURED_DATABASES:
        return
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
                  if not exists (
                    select 1
                    from information_schema.columns
                    where table_name = 'tenants' and column_name = 'api_mode'
                  ) then
                    alter table tenants add column api_mode text not null default 'system';
                  end if;
                  if not exists (
                    select 1
                    from information_schema.columns
                    where table_name = 'tenants' and column_name = 'api_ref'
                  ) then
                    alter table tenants add column api_ref jsonb not null default '{}'::jsonb;
                  end if;
                  alter table tenants alter column timeout_seconds set default 600;
                  update tenants
                  set timeout_seconds = 600
                  where timeout_seconds = 30;
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
                  if not exists (
                    select 1
                    from information_schema.columns
                    where table_name = 'workflow_runs' and column_name = 'trigger_mode'
                  ) then
                    alter table workflow_runs add column trigger_mode text not null default '';
                  end if;
                  if not exists (
                    select 1
                    from information_schema.columns
                    where table_name = 'workflow_runs' and column_name = 'current_node_index'
                  ) then
                    alter table workflow_runs add column current_node_index integer not null default 0;
                  end if;
                  if not exists (
                    select 1
                    from information_schema.columns
                    where table_name = 'workflow_runs' and column_name = 'total_node_count'
                  ) then
                    alter table workflow_runs add column total_node_count integer not null default 0;
                  end if;
                  if not exists (
                    select 1
                    from information_schema.tables
                    where table_name = 'tenant_wallets'
                  ) then
                    create table tenant_wallets (
                      id uuid primary key default gen_random_uuid(),
                      tenant_id text not null unique,
                      available_balance numeric(18,4) not null default 0,
                      total_recharged numeric(18,4) not null default 0,
                      total_consumed numeric(18,4) not null default 0,
                      currency text not null default 'CNY',
                      last_recharge_at timestamptz,
                      last_consume_at timestamptz,
                      last_synced_at timestamptz,
                      created_at timestamptz not null default now(),
                      updated_at timestamptz not null default now()
                    );
                  end if;
                  if not exists (
                    select 1
                    from information_schema.tables
                    where table_name = 'provider_usage_events'
                  ) then
                    create table provider_usage_events (
                      id uuid primary key default gen_random_uuid(),
                      tenant_id text not null,
                      provider text not null default '',
                      provider_event_id text not null default '',
                      request_id text not null default '',
                      channel text not null default '',
                      feature_key text not null default '',
                      model_name text not null default '',
                      tokens_in integer not null default 0,
                      tokens_out integer not null default 0,
                      image_count integer not null default 0,
                      amount numeric(18,4) not null default 0,
                      currency text not null default 'CNY',
                      related_resource_type text not null default '',
                      related_resource_id text not null default '',
                      ledger_entry_id uuid references wallet_ledger_entries(id) on delete set null,
                      status text not null default 'completed',
                      payload jsonb not null default '{}'::jsonb,
                      occurred_at timestamptz not null default now(),
                      created_at timestamptz not null default now(),
                      updated_at timestamptz not null default now()
                    );
                  end if;
                  if not exists (
                    select 1
                    from information_schema.columns
                    where table_name = 'wallet_ledger_entries' and column_name = 'metadata'
                  ) then
                    alter table wallet_ledger_entries add column metadata jsonb not null default '{}'::jsonb;
                  end if;
                  create index if not exists ix_tenant_wallets_balance
                  on tenant_wallets (available_balance desc, updated_at desc);
                  create unique index if not exists ux_provider_usage_events_provider_event
                  on provider_usage_events (tenant_id, provider, provider_event_id)
                  where provider <> '' and provider_event_id <> '';
                  create index if not exists ix_provider_usage_events_tenant_occurred
                  on provider_usage_events (tenant_id, occurred_at desc, created_at desc);
                  create index if not exists ix_provider_usage_events_tenant_channel
                  on provider_usage_events (tenant_id, channel, occurred_at desc);
                end $$;
                """
            )
            for statement in deprecated_tables_sql():
                cursor.execute(statement)
        connection.commit()
    _ENSURED_DATABASES.add(database_url)


def postgres_enabled(database_url: str | None) -> bool:
    return bool(str(database_url or "").strip())
