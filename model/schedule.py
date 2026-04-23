from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from model.db import connect_postgres
from model.types import TenantFlowSchedule


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
