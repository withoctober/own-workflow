from __future__ import annotations

from datetime import datetime
from typing import Any

from zoneinfo import ZoneInfo

from model.db import connect_postgres
from model.types import WorkflowRun


def _parse_timestamp(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    normalized = str(value).strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S")
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return parsed


def _build_workflow_run(row: dict[str, Any]) -> WorkflowRun:
    return WorkflowRun(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        flow_id=str(row["flow_id"]),
        batch_id=str(row["batch_id"]),
        source_url=str(row.get("source_url") or ""),
        status=str(row.get("status") or ""),
        current_node=str(row.get("current_node") or ""),
        current_node_index=int(row.get("current_node_index") or 0),
        total_node_count=int(row.get("total_node_count") or 0),
        resume_count=int(row.get("resume_count") or 0),
        completed_node_count=int(row.get("completed_node_count") or 0),
        error_count=int(row.get("error_count") or 0),
        last_message=str(row.get("last_message") or ""),
        last_error=str(row.get("last_error") or ""),
        started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def upsert_workflow_run(
    database_url: str,
    *,
    tenant_id: str,
    flow_id: str,
    batch_id: str,
    source_url: str = "",
    status: str = "",
    current_node: str = "",
    current_node_index: int = 0,
    total_node_count: int = 0,
    resume_count: int = 0,
    completed_node_count: int = 0,
    error_count: int = 0,
    last_message: str = "",
    last_error: str = "",
    started_at: str | datetime | None = None,
    finished_at: str | datetime | None = None,
) -> WorkflowRun:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into workflow_runs (
                  tenant_id,
                  flow_id,
                  batch_id,
                  source_url,
                  status,
                  current_node,
                  current_node_index,
                  total_node_count,
                  resume_count,
                  completed_node_count,
                  error_count,
                  last_message,
                  last_error,
                  started_at,
                  finished_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (tenant_id, flow_id, batch_id) do update set
                  source_url = excluded.source_url,
                  status = excluded.status,
                  current_node = excluded.current_node,
                  current_node_index = excluded.current_node_index,
                  total_node_count = excluded.total_node_count,
                  resume_count = excluded.resume_count,
                  completed_node_count = excluded.completed_node_count,
                  error_count = excluded.error_count,
                  last_message = excluded.last_message,
                  last_error = excluded.last_error,
                  started_at = coalesce(workflow_runs.started_at, excluded.started_at),
                  finished_at = excluded.finished_at,
                  updated_at = now()
                returning *
                """,
                (
                    tenant_id,
                    flow_id,
                    batch_id,
                    source_url,
                    status,
                    current_node,
                    current_node_index,
                    total_node_count,
                    resume_count,
                    completed_node_count,
                    error_count,
                    last_message,
                    last_error,
                    _parse_timestamp(started_at),
                    _parse_timestamp(finished_at),
                ),
            )
            row = cursor.fetchone()
        connection.commit()
    assert row is not None
    return _build_workflow_run(row)


def get_workflow_run(
    database_url: str,
    *,
    tenant_id: str,
    flow_id: str,
    batch_id: str,
) -> WorkflowRun | None:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select *
                from workflow_runs
                where tenant_id = %s
                  and flow_id = %s
                  and batch_id = %s
                limit 1
                """,
                (tenant_id, flow_id, batch_id),
            )
            row = cursor.fetchone()
    if row is None:
        return None
    return _build_workflow_run(row)


def list_workflow_runs(
    database_url: str,
    *,
    tenant_id: str,
    flow_id: str = "",
    status: str = "",
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[WorkflowRun], int]:
    normalized_flow_id = str(flow_id).strip()
    normalized_status = str(status).strip()
    safe_limit = max(1, min(int(limit), 200))
    safe_offset = max(0, int(offset))

    filters = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]
    if normalized_flow_id:
        filters.append("flow_id = %s")
        params.append(normalized_flow_id)
    if normalized_status:
        filters.append("status = %s")
        params.append(normalized_status)
    where_clause = " and ".join(filters)

    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                select count(*) as total
                from workflow_runs
                where {where_clause}
                """,
                params,
            )
            total_row = cursor.fetchone() or {"total": 0}
            cursor.execute(
                f"""
                select *
                from workflow_runs
                where {where_clause}
                order by updated_at desc, created_at desc
                limit %s
                offset %s
                """,
                [*params, safe_limit, safe_offset],
            )
            rows = cursor.fetchall()
    return ([_build_workflow_run(row) for row in rows], int(total_row.get("total") or 0))
