from __future__ import annotations

import json
from typing import Any

from model.db import connect_postgres
from model.types import Artifact


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _build_artifact(row: dict[str, Any]) -> Artifact:
    payload = row.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    return Artifact(
        id=str(row["id"]),
        tenant_id=str(row.get("tenant_id") or ""),
        flow_id=str(row.get("flow_id") or ""),
        batch_id=str(row.get("batch_id") or ""),
        workflow_run_id=str(row.get("workflow_run_id") or ""),
        artifact_type=str(row.get("artifact_type") or ""),
        title=str(row.get("title") or ""),
        content=str(row.get("content") or ""),
        tags=str(row.get("tags") or ""),
        cover_prompt=str(row.get("cover_prompt") or ""),
        cover_url=str(row.get("cover_url") or ""),
        image_prompts=_normalize_string_list(row.get("image_prompts")),
        image_urls=_normalize_string_list(row.get("image_urls")),
        source_url=str(row.get("source_url") or ""),
        payload=payload,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def upsert_artifact(
    database_url: str,
    *,
    tenant_id: str,
    flow_id: str,
    batch_id: str,
    artifact_type: str = "content",
    title: str = "",
    content: str = "",
    tags: str = "",
    cover_prompt: str = "",
    cover_url: str = "",
    image_prompts: list[str] | None = None,
    image_urls: list[str] | None = None,
    workflow_run_id: str = "",
    source_url: str = "",
    payload: dict[str, Any] | None = None,
) -> Artifact:
    normalized_payload = payload if isinstance(payload, dict) else {}
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into artifacts (
                  tenant_id,
                  flow_id,
                  batch_id,
                  workflow_run_id,
                  artifact_type,
                  title,
                  content,
                  tags,
                  cover_prompt,
                  cover_url,
                  image_prompts,
                  image_urls,
                  source_url,
                  payload
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb)
                on conflict (tenant_id, flow_id, batch_id, artifact_type) do update set
                  workflow_run_id = excluded.workflow_run_id,
                  title = excluded.title,
                  content = excluded.content,
                  tags = excluded.tags,
                  cover_prompt = excluded.cover_prompt,
                  cover_url = excluded.cover_url,
                  image_prompts = excluded.image_prompts,
                  image_urls = excluded.image_urls,
                  source_url = excluded.source_url,
                  payload = excluded.payload,
                  updated_at = now()
                returning *
                """,
                (
                    tenant_id,
                    flow_id,
                    batch_id,
                    workflow_run_id,
                    artifact_type,
                    title,
                    content,
                    tags,
                    cover_prompt,
                    cover_url,
                    json.dumps(_normalize_string_list(image_prompts)),
                    json.dumps(_normalize_string_list(image_urls)),
                    source_url,
                    json.dumps(normalized_payload, ensure_ascii=False),
                ),
            )
            row = cursor.fetchone()
        connection.commit()
    assert row is not None
    return _build_artifact(row)


def get_artifact(
    database_url: str,
    *,
    tenant_id: str,
    artifact_id: str,
) -> Artifact | None:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select *
                from artifacts
                where tenant_id = %s
                  and id = %s
                limit 1
                """,
                (tenant_id, artifact_id),
            )
            row = cursor.fetchone()
    if row is None:
        return None
    return _build_artifact(row)


def update_artifact(
    database_url: str,
    *,
    tenant_id: str,
    artifact_id: str,
    title: str | None = None,
    content: str | None = None,
    tags: str | None = None,
    cover_prompt: str | None = None,
    cover_url: str | None = None,
    image_prompts: list[str] | None = None,
    image_urls: list[str] | None = None,
    payload: dict[str, Any] | None = None,
) -> Artifact | None:
    current = get_artifact(database_url, tenant_id=tenant_id, artifact_id=artifact_id)
    if current is None:
        return None

    normalized_payload = current.payload if isinstance(current.payload, dict) else {}
    if isinstance(payload, dict):
        normalized_payload = payload

    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update artifacts
                set
                  title = %s,
                  content = %s,
                  tags = %s,
                  cover_prompt = %s,
                  cover_url = %s,
                  image_prompts = %s::jsonb,
                  image_urls = %s::jsonb,
                  payload = %s::jsonb,
                  updated_at = now()
                where tenant_id = %s
                  and id = %s
                returning *
                """,
                (
                    title if title is not None else current.title,
                    content if content is not None else current.content,
                    tags if tags is not None else current.tags,
                    cover_prompt if cover_prompt is not None else current.cover_prompt,
                    cover_url if cover_url is not None else current.cover_url,
                    json.dumps(_normalize_string_list(image_prompts if image_prompts is not None else current.image_prompts)),
                    json.dumps(_normalize_string_list(image_urls if image_urls is not None else current.image_urls)),
                    json.dumps(normalized_payload, ensure_ascii=False),
                    tenant_id,
                    artifact_id,
                ),
            )
            row = cursor.fetchone()
        connection.commit()

    if row is None:
        return None
    return _build_artifact(row)


def list_artifacts(
    database_url: str,
    *,
    tenant_id: str,
    flow_id: str = "",
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Artifact], int]:
    normalized_flow_id = str(flow_id).strip()
    safe_limit = max(1, min(int(limit), 200))
    safe_offset = max(0, int(offset))

    filters = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]
    if normalized_flow_id:
        filters.append("flow_id = %s")
        params.append(normalized_flow_id)
    where_clause = " and ".join(filters)

    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                select count(*) as total
                from artifacts
                where {where_clause}
                """,
                params,
            )
            total_row = cursor.fetchone() or {"total": 0}
            cursor.execute(
                f"""
                select *
                from artifacts
                where {where_clause}
                order by updated_at desc, created_at desc
                limit %s
                offset %s
                """,
                [*params, safe_limit, safe_offset],
            )
            rows = cursor.fetchall()
    return ([_build_artifact(row) for row in rows], int(total_row.get("total") or 0))


def delete_artifact(
    database_url: str,
    *,
    tenant_id: str,
    artifact_id: str,
) -> bool:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                delete from artifacts
                where tenant_id = %s
                  and id = %s
                returning id
                """,
                (tenant_id, artifact_id),
            )
            row = cursor.fetchone()
        connection.commit()
    return row is not None


def update_artifact(
    database_url: str,
    *,
    tenant_id: str,
    artifact_id: str,
    title: str = "",
    content: str = "",
    tags: str = "",
    cover_prompt: str = "",
    cover_url: str = "",
    image_prompts: list[str] | None = None,
    image_urls: list[str] | None = None,
    payload: dict[str, Any] | None = None,
) -> Artifact | None:
    normalized_payload = payload if isinstance(payload, dict) else {}
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update artifacts
                set
                  title = %s,
                  content = %s,
                  tags = %s,
                  cover_prompt = %s,
                  cover_url = %s,
                  image_prompts = %s::jsonb,
                  image_urls = %s::jsonb,
                  payload = %s::jsonb,
                  updated_at = now()
                where tenant_id = %s
                  and id = %s
                returning *
                """,
                (
                    title,
                    content,
                    tags,
                    cover_prompt,
                    cover_url,
                    json.dumps(_normalize_string_list(image_prompts)),
                    json.dumps(_normalize_string_list(image_urls)),
                    json.dumps(normalized_payload, ensure_ascii=False),
                    tenant_id,
                    artifact_id,
                ),
            )
            row = cursor.fetchone()
        connection.commit()
    if row is None:
        return None
    return _build_artifact(row)
