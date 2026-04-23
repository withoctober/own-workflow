from __future__ import annotations

import json
from typing import Any

from model.db import connect_postgres
from model.types import StoreEntry


def _build_store_entry(row: dict[str, Any]) -> StoreEntry:
    payload = row.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    return StoreEntry(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        dataset_key=str(row["dataset_key"]),
        entry_type=str(row["entry_type"]),
        record_key=str(row.get("record_key") or ""),
        title=str(row.get("title") or ""),
        batch_id=str(row.get("batch_id") or ""),
        sort_order=int(row.get("sort_order") or 0),
        content_text=str(row.get("content_text") or ""),
        payload=payload,
        schema_version=int(row.get("schema_version") or 1),
        source_ref=str(row.get("source_ref") or ""),
        is_deleted=bool(row.get("is_deleted") or False),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def list_store_entries(
    database_url: str,
    *,
    tenant_id: str,
    dataset_key: str,
    entry_type: str,
) -> list[StoreEntry]:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select *
                from store_entries
                where tenant_id = %s
                  and dataset_key = %s
                  and entry_type = %s
                  and is_deleted = false
                order by sort_order asc, created_at asc
                """,
                (tenant_id, dataset_key, entry_type),
            )
            rows = cursor.fetchall()
    return [_build_store_entry(row) for row in rows]


def get_store_entry(
    database_url: str,
    *,
    tenant_id: str,
    dataset_key: str,
    entry_type: str,
    record_key: str,
) -> StoreEntry | None:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select *
                from store_entries
                where tenant_id = %s
                  and dataset_key = %s
                  and entry_type = %s
                  and record_key = %s
                  and is_deleted = false
                limit 1
                """,
                (tenant_id, dataset_key, entry_type, record_key),
            )
            row = cursor.fetchone()
    if not row:
        return None
    return _build_store_entry(row)


def soft_delete_store_entries(
    database_url: str,
    *,
    tenant_id: str,
    dataset_key: str,
    entry_type: str,
) -> int:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update store_entries
                set is_deleted = true,
                    updated_at = now()
                where tenant_id = %s
                  and dataset_key = %s
                  and entry_type = %s
                  and is_deleted = false
                """,
                (tenant_id, dataset_key, entry_type),
            )
            count = cursor.rowcount
        connection.commit()
    return count


def soft_delete_store_entry(
    database_url: str,
    *,
    tenant_id: str,
    dataset_key: str,
    entry_type: str,
    record_key: str,
) -> bool:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update store_entries
                set is_deleted = true,
                    updated_at = now()
                where tenant_id = %s
                  and dataset_key = %s
                  and entry_type = %s
                  and record_key = %s
                  and is_deleted = false
                """,
                (tenant_id, dataset_key, entry_type, record_key),
            )
            deleted = cursor.rowcount > 0
        connection.commit()
    return deleted


def insert_store_rows(
    database_url: str,
    *,
    tenant_id: str,
    dataset_key: str,
    rows: list[dict[str, Any]],
) -> list[StoreEntry]:
    inserted: list[StoreEntry] = []
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            for index, row in enumerate(rows):
                payload = dict(row)
                record_key = str(payload.pop("record_id", "")).strip() or f"row-{index + 1}-{abs(hash(json.dumps(row, ensure_ascii=False, sort_keys=True)))}"
                title = str(payload.get("标题") or payload.get("title") or payload.get("日期") or "").strip()
                batch_id = str(payload.get("batch_id") or "").strip()
                source_ref = str(payload.get("source_ref") or "").strip()
                cursor.execute(
                    """
                    insert into store_entries (
                      tenant_id,
                      dataset_key,
                      entry_type,
                      record_key,
                      title,
                      batch_id,
                      sort_order,
                      payload,
                      source_ref
                    )
                    values (%s, %s, 'row', %s, %s, %s, %s, %s::jsonb, %s)
                    returning *
                    """,
                    (
                        tenant_id,
                        dataset_key,
                        record_key,
                        title,
                        batch_id,
                        index,
                        json.dumps(payload, ensure_ascii=False),
                        source_ref,
                    ),
                )
                inserted_row = cursor.fetchone()
                assert inserted_row is not None
                inserted.append(_build_store_entry(inserted_row))
        connection.commit()
    return inserted


def update_store_rows(
    database_url: str,
    *,
    tenant_id: str,
    dataset_key: str,
    rows: list[dict[str, Any]],
) -> list[StoreEntry]:
    updated: list[StoreEntry] = []
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            for row in rows:
                payload = dict(row)
                record_id = str(payload.pop("record_id", "")).strip()
                if not record_id:
                    continue
                title = str(payload.get("标题") or payload.get("title") or payload.get("日期") or "").strip()
                batch_id = str(payload.get("batch_id") or "").strip()
                source_ref = str(payload.get("source_ref") or "").strip()
                cursor.execute(
                    """
                    update store_entries
                    set title = %s,
                        batch_id = %s,
                        payload = %s::jsonb,
                        source_ref = %s,
                        updated_at = now()
                    where tenant_id = %s
                      and dataset_key = %s
                      and entry_type = 'row'
                      and record_key = %s
                      and is_deleted = false
                    returning *
                    """,
                    (
                        title,
                        batch_id,
                        json.dumps(payload, ensure_ascii=False),
                        source_ref,
                        tenant_id,
                        dataset_key,
                        record_id,
                    ),
                )
                updated_row = cursor.fetchone()
                if updated_row is not None:
                    updated.append(_build_store_entry(updated_row))
        connection.commit()
    return updated


def upsert_store_doc(
    database_url: str,
    *,
    tenant_id: str,
    dataset_key: str,
    content_text: str,
    title: str,
    batch_id: str = "",
    source_ref: str = "",
) -> StoreEntry:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into store_entries (
                  tenant_id,
                  dataset_key,
                  entry_type,
                  record_key,
                  title,
                  batch_id,
                  content_text,
                  payload,
                  source_ref
                )
                values (%s, %s, 'doc', '__doc__', %s, %s, %s, '{}'::jsonb, %s)
                on conflict (tenant_id, dataset_key, entry_type, record_key)
                where is_deleted = false
                do update set
                  title = excluded.title,
                  batch_id = excluded.batch_id,
                  content_text = excluded.content_text,
                  source_ref = excluded.source_ref,
                  updated_at = now()
                returning *
                """,
                (
                    tenant_id,
                    dataset_key,
                    title,
                    batch_id,
                    content_text,
                    source_ref,
                ),
            )
            row = cursor.fetchone()
        connection.commit()
    assert row is not None
    return _build_store_entry(row)
