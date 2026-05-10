from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from model.db import connect_postgres
from model.types import ProviderUsageEvent, TenantWallet, WalletLedgerEntry


def _to_datetime(value: datetime | str | None, *, end_of_day: bool = False) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    raw = str(value).strip()
    parsed = datetime.fromisoformat(raw)
    if end_of_day and "T" not in raw and " " not in raw:
        return parsed + timedelta(days=1, microseconds=-1)
    return parsed


def _to_float(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    if value is None or value == "":
        return 0.0
    return float(value)


def _to_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    return int(value)


def _build_wallet_ledger_entry(row: dict[str, Any]) -> WalletLedgerEntry:
    metadata = row.get("metadata")
    return WalletLedgerEntry(
        id=str(row["id"]),
        tenant_id=str(row.get("tenant_id") or ""),
        entry_type=str(row.get("entry_type") or ""),
        amount=_to_float(row.get("amount")),
        title=str(row.get("title") or ""),
        channel=str(row.get("channel") or ""),
        provider=str(row.get("provider") or ""),
        provider_event_id=str(row.get("provider_event_id") or ""),
        related_resource_type=str(row.get("related_resource_type") or ""),
        related_resource_id=str(row.get("related_resource_id") or ""),
        status=str(row.get("status") or ""),
        detail=str(row.get("detail") or ""),
        metadata=metadata if isinstance(metadata, dict) else {},
        occurred_at=row.get("occurred_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _build_tenant_wallet(row: dict[str, Any]) -> TenantWallet:
    return TenantWallet(
        id=str(row["id"]),
        tenant_id=str(row.get("tenant_id") or ""),
        available_balance=_to_float(row.get("available_balance")),
        total_recharged=_to_float(row.get("total_recharged")),
        total_consumed=_to_float(row.get("total_consumed")),
        currency=str(row.get("currency") or "CNY"),
        last_recharge_at=row.get("last_recharge_at"),
        last_consume_at=row.get("last_consume_at"),
        last_synced_at=row.get("last_synced_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _build_provider_usage_event(row: dict[str, Any]) -> ProviderUsageEvent:
    payload = row.get("payload")
    return ProviderUsageEvent(
        id=str(row["id"]),
        tenant_id=str(row.get("tenant_id") or ""),
        provider=str(row.get("provider") or ""),
        provider_event_id=str(row.get("provider_event_id") or ""),
        request_id=str(row.get("request_id") or ""),
        channel=str(row.get("channel") or ""),
        feature_key=str(row.get("feature_key") or ""),
        model_name=str(row.get("model_name") or ""),
        tokens_in=_to_int(row.get("tokens_in")),
        tokens_out=_to_int(row.get("tokens_out")),
        image_count=_to_int(row.get("image_count")),
        amount=_to_float(row.get("amount")),
        currency=str(row.get("currency") or "CNY"),
        related_resource_type=str(row.get("related_resource_type") or ""),
        related_resource_id=str(row.get("related_resource_id") or ""),
        ledger_entry_id=str(row.get("ledger_entry_id") or ""),
        status=str(row.get("status") or ""),
        payload=payload if isinstance(payload, dict) else {},
        occurred_at=row.get("occurred_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def ensure_tenant_wallet(database_url: str, *, tenant_id: str, currency: str = "CNY") -> TenantWallet:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into tenant_wallets (tenant_id, currency)
                values (%s, %s)
                on conflict (tenant_id) do update set
                  currency = coalesce(nullif(excluded.currency, ''), tenant_wallets.currency),
                  updated_at = tenant_wallets.updated_at
                returning *
                """,
                (tenant_id, currency or "CNY"),
            )
            row = cursor.fetchone()
        connection.commit()
    assert row is not None
    return _build_tenant_wallet(row)


def get_tenant_wallet(database_url: str, *, tenant_id: str) -> TenantWallet | None:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select *
                from tenant_wallets
                where tenant_id = %s
                limit 1
                """,
                (tenant_id,),
            )
            row = cursor.fetchone()
    if row is None:
        return None
    return _build_tenant_wallet(row)


def sync_tenant_wallet_balance(database_url: str, *, tenant_id: str) -> TenantWallet:
    ensure_tenant_wallet(database_url, tenant_id=tenant_id)
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                with stats as (
                  select
                    coalesce(sum(case when amount > 0 and status in ('completed', 'settled') then amount else 0 end), 0) as total_recharged,
                    coalesce(sum(case when amount < 0 and status in ('completed', 'settled') then -amount else 0 end), 0) as total_consumed,
                    max(case when amount > 0 and status in ('completed', 'settled') then occurred_at end) as last_recharge_at,
                    max(case when amount < 0 and status in ('completed', 'settled') then occurred_at end) as last_consume_at
                  from wallet_ledger_entries
                  where tenant_id = %s
                )
                update tenant_wallets
                set
                  total_recharged = stats.total_recharged,
                  total_consumed = stats.total_consumed,
                  available_balance = stats.total_recharged - stats.total_consumed,
                  last_recharge_at = stats.last_recharge_at,
                  last_consume_at = stats.last_consume_at,
                  last_synced_at = now(),
                  updated_at = now()
                from stats
                where tenant_wallets.tenant_id = %s
                returning tenant_wallets.*
                """,
                (tenant_id, tenant_id),
            )
            row = cursor.fetchone()
        connection.commit()
    assert row is not None
    return _build_tenant_wallet(row)


def create_wallet_ledger_entry(
    database_url: str,
    *,
    tenant_id: str,
    entry_type: str,
    amount: float,
    title: str,
    channel: str = "",
    provider: str = "",
    provider_event_id: str = "",
    related_resource_type: str = "",
    related_resource_id: str = "",
    status: str = "completed",
    detail: str = "",
    metadata: dict[str, Any] | None = None,
    occurred_at: datetime | str | None = None,
) -> WalletLedgerEntry:
    normalized_metadata = metadata if isinstance(metadata, dict) else {}
    ensure_tenant_wallet(database_url, tenant_id=tenant_id)
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into wallet_ledger_entries (
                  tenant_id,
                  entry_type,
                  amount,
                  title,
                  channel,
                  provider,
                  provider_event_id,
                  related_resource_type,
                  related_resource_id,
                  status,
                  detail,
                  metadata,
                  occurred_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, coalesce(%s, now()))
                on conflict (tenant_id, provider, provider_event_id)
                where provider <> '' and provider_event_id <> ''
                do update set
                  entry_type = excluded.entry_type,
                  amount = excluded.amount,
                  title = excluded.title,
                  channel = excluded.channel,
                  related_resource_type = excluded.related_resource_type,
                  related_resource_id = excluded.related_resource_id,
                  status = excluded.status,
                  detail = excluded.detail,
                  metadata = excluded.metadata,
                  occurred_at = excluded.occurred_at,
                  updated_at = now()
                returning *
                """,
                (
                    tenant_id,
                    entry_type,
                    amount,
                    title,
                    channel,
                    provider,
                    provider_event_id,
                    related_resource_type,
                    related_resource_id,
                    status,
                    detail,
                    json.dumps(normalized_metadata, ensure_ascii=False),
                    _to_datetime(occurred_at),
                ),
            )
            row = cursor.fetchone()
        connection.commit()
    assert row is not None
    sync_tenant_wallet_balance(database_url, tenant_id=tenant_id)
    return _build_wallet_ledger_entry(row)


def create_provider_usage_event(
    database_url: str,
    *,
    tenant_id: str,
    provider: str,
    provider_event_id: str = "",
    request_id: str = "",
    channel: str = "",
    feature_key: str = "",
    model_name: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
    image_count: int = 0,
    amount: float = 0.0,
    currency: str = "CNY",
    related_resource_type: str = "",
    related_resource_id: str = "",
    ledger_entry_id: str = "",
    status: str = "completed",
    payload: dict[str, Any] | None = None,
    occurred_at: datetime | str | None = None,
) -> ProviderUsageEvent:
    normalized_payload = payload if isinstance(payload, dict) else {}
    ensure_tenant_wallet(database_url, tenant_id=tenant_id, currency=currency or "CNY")
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into provider_usage_events (
                  tenant_id,
                  provider,
                  provider_event_id,
                  request_id,
                  channel,
                  feature_key,
                  model_name,
                  tokens_in,
                  tokens_out,
                  image_count,
                  amount,
                  currency,
                  related_resource_type,
                  related_resource_id,
                  ledger_entry_id,
                  status,
                  payload,
                  occurred_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, nullif(%s, '')::uuid, %s, %s::jsonb, coalesce(%s, now()))
                on conflict (tenant_id, provider, provider_event_id)
                where provider <> '' and provider_event_id <> ''
                do update set
                  request_id = excluded.request_id,
                  channel = excluded.channel,
                  feature_key = excluded.feature_key,
                  model_name = excluded.model_name,
                  tokens_in = excluded.tokens_in,
                  tokens_out = excluded.tokens_out,
                  image_count = excluded.image_count,
                  amount = excluded.amount,
                  currency = excluded.currency,
                  related_resource_type = excluded.related_resource_type,
                  related_resource_id = excluded.related_resource_id,
                  ledger_entry_id = excluded.ledger_entry_id,
                  status = excluded.status,
                  payload = excluded.payload,
                  occurred_at = excluded.occurred_at,
                  updated_at = now()
                returning *
                """,
                (
                    tenant_id,
                    provider,
                    provider_event_id,
                    request_id,
                    channel,
                    feature_key,
                    model_name,
                    max(0, int(tokens_in)),
                    max(0, int(tokens_out)),
                    max(0, int(image_count)),
                    amount,
                    currency or "CNY",
                    related_resource_type,
                    related_resource_id,
                    ledger_entry_id,
                    status,
                    json.dumps(normalized_payload, ensure_ascii=False),
                    _to_datetime(occurred_at),
                ),
            )
            row = cursor.fetchone()
        connection.commit()
    assert row is not None
    return _build_provider_usage_event(row)


def list_provider_usage_events(
    database_url: str,
    *,
    tenant_id: str,
    provider: str = "",
    channel: str = "",
    date_from: datetime | str | None = None,
    date_to: datetime | str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[ProviderUsageEvent], int]:
    filters = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]

    normalized_provider = str(provider).strip()
    if normalized_provider:
        filters.append("provider = %s")
        params.append(normalized_provider)

    normalized_channel = str(channel).strip()
    if normalized_channel:
        filters.append("channel = %s")
        params.append(normalized_channel)

    parsed_from = _to_datetime(date_from)
    if parsed_from is not None:
        filters.append("occurred_at >= %s")
        params.append(parsed_from)

    parsed_to = _to_datetime(date_to, end_of_day=True)
    if parsed_to is not None:
        filters.append("occurred_at <= %s")
        params.append(parsed_to)

    where_clause = " and ".join(filters)
    safe_limit = max(1, min(int(limit), 500))
    safe_offset = max(0, int(offset))

    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                select count(*) as total
                from provider_usage_events
                where {where_clause}
                """,
                params,
            )
            total_row = cursor.fetchone() or {"total": 0}
            cursor.execute(
                f"""
                select *
                from provider_usage_events
                where {where_clause}
                order by occurred_at desc, created_at desc
                limit %s
                offset %s
                """,
                [*params, safe_limit, safe_offset],
            )
            rows = cursor.fetchall()
    return ([_build_provider_usage_event(row) for row in rows], int(total_row.get("total") or 0))


def attach_provider_usage_to_ledger(
    database_url: str,
    *,
    tenant_id: str,
    provider: str,
    provider_event_id: str,
    ledger_entry_id: str,
) -> ProviderUsageEvent | None:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update provider_usage_events
                set
                  ledger_entry_id = %s::uuid,
                  updated_at = now()
                where tenant_id = %s
                  and provider = %s
                  and provider_event_id = %s
                returning *
                """,
                (ledger_entry_id, tenant_id, provider, provider_event_id),
            )
            row = cursor.fetchone()
        connection.commit()
    if row is None:
        return None
    return _build_provider_usage_event(row)


def hydrate_provider_usage_from_ledger(database_url: str, *, tenant_id: str) -> int:
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into provider_usage_events (
                  tenant_id,
                  provider,
                  provider_event_id,
                  request_id,
                  channel,
                  feature_key,
                  model_name,
                  tokens_in,
                  tokens_out,
                  image_count,
                  amount,
                  currency,
                  related_resource_type,
                  related_resource_id,
                  ledger_entry_id,
                  status,
                  payload,
                  occurred_at
                )
                select
                  ledger.tenant_id,
                  ledger.provider,
                  ledger.provider_event_id,
                  coalesce(ledger.metadata->>'request_id', ''),
                  ledger.channel,
                  coalesce(ledger.metadata->>'feature', ''),
                  coalesce(ledger.metadata->>'model_name', ''),
                  coalesce(nullif(ledger.metadata->>'tokens_in', ''), '0')::integer,
                  coalesce(nullif(ledger.metadata->>'tokens_out', ''), '0')::integer,
                  coalesce(nullif(ledger.metadata->>'image_count', ''), '0')::integer,
                  case when ledger.amount < 0 then -ledger.amount else ledger.amount end,
                  coalesce(nullif(ledger.metadata->>'currency', ''), 'CNY'),
                  ledger.related_resource_type,
                  ledger.related_resource_id,
                  ledger.id,
                  ledger.status,
                  ledger.metadata,
                  ledger.occurred_at
                from wallet_ledger_entries as ledger
                where ledger.tenant_id = %s
                  and ledger.provider <> ''
                  and ledger.provider_event_id <> ''
                  and not exists (
                    select 1
                    from provider_usage_events as usage
                    where usage.tenant_id = ledger.tenant_id
                      and usage.provider = ledger.provider
                      and usage.provider_event_id = ledger.provider_event_id
                  )
                """,
                (tenant_id,),
            )
            inserted = int(cursor.rowcount or 0)
        connection.commit()
    return inserted


def list_wallet_ledger_entries(
    database_url: str,
    *,
    tenant_id: str,
    entry_type: str = "",
    date_from: datetime | str | None = None,
    date_to: datetime | str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[WalletLedgerEntry], int]:
    filters = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]

    normalized_type = str(entry_type).strip()
    if normalized_type:
        filters.append("entry_type = %s")
        params.append(normalized_type)

    parsed_from = _to_datetime(date_from)
    if parsed_from is not None:
        filters.append("occurred_at >= %s")
        params.append(parsed_from)

    parsed_to = _to_datetime(date_to, end_of_day=True)
    if parsed_to is not None:
        filters.append("occurred_at <= %s")
        params.append(parsed_to)

    where_clause = " and ".join(filters)
    safe_limit = max(1, min(int(limit), 500))
    safe_offset = max(0, int(offset))

    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                select *,
                  count(*) over() as total_count
                from wallet_ledger_entries
                where {where_clause}
                order by occurred_at desc, created_at desc
                limit %s
                offset %s
                """,
                [*params, safe_limit, safe_offset],
            )
            rows = cursor.fetchall()
            if rows:
                total = int(rows[0].get("total_count") or 0)
            elif safe_offset > 0:
                cursor.execute(
                    f"""
                    select count(*) as total
                    from wallet_ledger_entries
                    where {where_clause}
                    """,
                    params,
                )
                total_row = cursor.fetchone() or {"total": 0}
                total = int(total_row.get("total") or 0)
            else:
                total = 0
    return ([_build_wallet_ledger_entry(row) for row in rows], total)


def summarize_wallet_balance(
    database_url: str,
    *,
    tenant_id: str,
) -> dict[str, float]:
    wallet = get_tenant_wallet(database_url, tenant_id=tenant_id)
    if wallet is None:
        wallet = sync_tenant_wallet_balance(database_url, tenant_id=tenant_id)
    return {
        "balance": wallet.available_balance,
        "recharge_total": wallet.total_recharged,
        "consume_total": wallet.total_consumed,
    }


def summarize_wallet_period(
    database_url: str,
    *,
    tenant_id: str,
    date_from: datetime | str | None = None,
    date_to: datetime | str | None = None,
) -> dict[str, float]:
    filters = ["tenant_id = %s", "status in ('completed', 'settled')"]
    params: list[Any] = [tenant_id]

    parsed_from = _to_datetime(date_from)
    if parsed_from is not None:
        filters.append("occurred_at >= %s")
        params.append(parsed_from)

    parsed_to = _to_datetime(date_to, end_of_day=True)
    if parsed_to is not None:
        filters.append("occurred_at <= %s")
        params.append(parsed_to)

    where_clause = " and ".join(filters)
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                select
                  coalesce(sum(case when amount < 0 then -amount else 0 end), 0) as consume_total,
                  coalesce(sum(case when amount > 0 then amount else 0 end), 0) as recharge_total
                from wallet_ledger_entries
                where {where_clause}
                """,
                params,
            )
            row = cursor.fetchone() or {}
    return {
        "consume_total": _to_float(row.get("consume_total")),
        "recharge_total": _to_float(row.get("recharge_total")),
    }


def summarize_wallet_breakdown(
    database_url: str,
    *,
    tenant_id: str,
    date_from: datetime | str | None = None,
    date_to: datetime | str | None = None,
) -> list[dict[str, Any]]:
    filters = ["tenant_id = %s", "amount < 0", "status in ('completed', 'settled')"]
    params: list[Any] = [tenant_id]

    parsed_from = _to_datetime(date_from)
    if parsed_from is not None:
        filters.append("occurred_at >= %s")
        params.append(parsed_from)

    parsed_to = _to_datetime(date_to, end_of_day=True)
    if parsed_to is not None:
        filters.append("occurred_at <= %s")
        params.append(parsed_to)

    where_clause = " and ".join(filters)
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                select
                  channel,
                  coalesce(sum(-amount), 0) as amount,
                  count(*) as entry_count
                from wallet_ledger_entries
                where {where_clause}
                group by channel
                order by amount desc, channel asc
                """,
                params,
            )
            rows = cursor.fetchall()
    return [
        {
            "channel": str(row.get("channel") or "未分类"),
            "amount": _to_float(row.get("amount")),
            "entry_count": int(row.get("entry_count") or 0),
        }
        for row in rows
    ]


def summarize_wallet_daily_usage(
    database_url: str,
    *,
    tenant_id: str,
    date_from: datetime | str | None = None,
    date_to: datetime | str | None = None,
) -> list[dict[str, Any]]:
    filters = ["tenant_id = %s", "amount < 0", "status in ('completed', 'settled')"]
    params: list[Any] = [tenant_id]

    parsed_from = _to_datetime(date_from)
    if parsed_from is not None:
        filters.append("occurred_at >= %s")
        params.append(parsed_from)

    parsed_to = _to_datetime(date_to, end_of_day=True)
    if parsed_to is not None:
        filters.append("occurred_at <= %s")
        params.append(parsed_to)

    where_clause = " and ".join(filters)
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                select
                  to_char(date_trunc('day', occurred_at), 'YYYY-MM-DD') as usage_date,
                  coalesce(sum(-amount), 0) as amount
                from wallet_ledger_entries
                where {where_clause}
                group by date_trunc('day', occurred_at)
                order by date_trunc('day', occurred_at) asc
                """,
                params,
            )
            rows = cursor.fetchall()
    return [
        {
            "date": str(row.get("usage_date") or ""),
            "amount": _to_float(row.get("amount")),
        }
        for row in rows
    ]


def summarize_provider_usage_amount(
    database_url: str,
    *,
    tenant_id: str,
    provider: str,
    channel: str = "",
    date_from: datetime | str | None = None,
    date_to: datetime | str | None = None,
) -> float:
    filters = ["tenant_id = %s", "provider = %s", "status in ('completed', 'settled')"]
    params: list[Any] = [tenant_id, provider]

    normalized_channel = str(channel).strip()
    if normalized_channel:
        filters.append("channel = %s")
        params.append(normalized_channel)

    parsed_from = _to_datetime(date_from)
    if parsed_from is not None:
        filters.append("occurred_at >= %s")
        params.append(parsed_from)

    parsed_to = _to_datetime(date_to, end_of_day=True)
    if parsed_to is not None:
        filters.append("occurred_at <= %s")
        params.append(parsed_to)

    where_clause = " and ".join(filters)
    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                select coalesce(sum(amount), 0) as total_amount
                from provider_usage_events
                where {where_clause}
                """,
                params,
            )
            row = cursor.fetchone() or {}
    return _to_float(row.get("total_amount"))


def summarize_provider_usage_windows(
    database_url: str,
    *,
    tenant_id: str,
    provider_channels: list[tuple[str, str]],
    today_from: datetime | str,
    week_from: datetime | str,
    month_from: datetime | str,
) -> dict[tuple[str, str], dict[str, Any]]:
    normalized_pairs: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for provider, channel in provider_channels:
        normalized_provider = str(provider).strip()
        if not normalized_provider:
            continue
        normalized_pair = (normalized_provider, str(channel).strip())
        if normalized_pair in seen_pairs:
            continue
        seen_pairs.add(normalized_pair)
        normalized_pairs.append(normalized_pair)

    if not normalized_pairs:
        return {}

    parsed_today = _to_datetime(today_from) or datetime.now()
    parsed_week = _to_datetime(week_from) or parsed_today
    parsed_month = _to_datetime(month_from) or parsed_week

    values_sql = ", ".join(["(%s, %s)"] * len(normalized_pairs))
    value_params: list[Any] = []
    for provider, channel in normalized_pairs:
        value_params.extend([provider, channel])

    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                with requested(provider, channel) as (
                  values {values_sql}
                )
                select
                  requested.provider,
                  requested.channel,
                  coalesce(
                    sum(
                      case
                        when usage.status in ('completed', 'settled') and usage.occurred_at >= %s
                          then usage.amount
                        else 0
                      end
                    ),
                    0
                  ) as today_amount,
                  coalesce(
                    sum(
                      case
                        when usage.status in ('completed', 'settled') and usage.occurred_at >= %s
                          then usage.amount
                        else 0
                      end
                    ),
                    0
                  ) as week_amount,
                  coalesce(
                    sum(
                      case
                        when usage.status in ('completed', 'settled') and usage.occurred_at >= %s
                          then usage.amount
                        else 0
                      end
                    ),
                    0
                  ) as month_amount,
                  max(usage.updated_at) as last_synced_at
                from requested
                left join provider_usage_events as usage
                  on usage.tenant_id = %s
                 and usage.provider = requested.provider
                 and coalesce(usage.channel, '') = requested.channel
                group by requested.provider, requested.channel
                """,
                value_params + [parsed_today, parsed_week, parsed_month, tenant_id],
            )
            rows = cursor.fetchall()

    summary: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        provider = str(row.get("provider") or "")
        channel = str(row.get("channel") or "")
        summary[(provider, channel)] = {
            "today": _to_float(row.get("today_amount")),
            "week": _to_float(row.get("week_amount")),
            "month": _to_float(row.get("month_amount")),
            "last_synced_at": row.get("last_synced_at") if isinstance(row.get("last_synced_at"), datetime) else None,
        }
    return summary


def get_provider_usage_last_synced_at(
    database_url: str,
    *,
    tenant_id: str,
    provider: str,
    channel: str = "",
) -> datetime | None:
    filters = ["tenant_id = %s", "provider = %s"]
    params: list[Any] = [tenant_id, provider]
    normalized_channel = str(channel).strip()
    if normalized_channel:
        filters.append("channel = %s")
        params.append(normalized_channel)
    where_clause = " and ".join(filters)

    with connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                select max(updated_at) as last_synced_at
                from provider_usage_events
                where {where_clause}
                """,
                params,
            )
            row = cursor.fetchone() or {}
    value = row.get("last_synced_at")
    return value if isinstance(value, datetime) else None
