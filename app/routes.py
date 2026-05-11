from __future__ import annotations

from datetime import datetime, timedelta
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
from threading import Lock
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_runtime, get_settings, load_run_state, require_tenant_api_key
from model import (
    create_provider_usage_event,
    create_wallet_ledger_entry,
    delete_artifact,
    delete_tenant_flow_schedule,
    ensure_tenant_wallet,
    ensure_postgres_tables,
    generate_tenant_id,
    get_artifact,
    get_store_entry,
    get_tenant_by_api_key,
    get_tenant_flow_schedule,
    get_tenant_runtime_config,
    get_tenant_by_id,
    insert_store_rows,
    hydrate_provider_usage_from_ledger,
    list_artifacts,
    list_provider_usage_events,
    list_wallet_ledger_entries,
    list_workflow_runs,
    list_tenant_flow_schedules,
    list_tenants,
    list_store_entries,
    postgres_enabled,
    soft_delete_store_entry,
    summarize_wallet_balance,
    summarize_wallet_breakdown,
    summarize_wallet_daily_usage,
    summarize_provider_usage_windows,
    summarize_wallet_period,
    sync_tenant_wallet_balance,
    update_artifact,
    upsert_tenant_flow_schedule,
    upsert_tenant,
    update_store_rows,
)
from app.schemas import (
    ArtifactListResponse,
    ArtifactPreviewImageEditRequest,
    ArtifactRegenerateImageRequest,
    ArtifactResponse,
    ArtifactUpdateRequest,
    CreateTenantRequest,
    DatasetTableCatalogItemResponse,
    DatasetTableCatalogResponse,
    DatasetTableListResponse,
    DatasetTableRowRequest,
    DatasetTableRowResponse,
    ResolveSpaceRequest,
    ResolveSpaceResponse,
    RunFlowRequest,
    TenantFlowScheduleListResponse,
    TenantFlowScheduleResponse,
    TenantCredentialConfigResponse,
    TenantResponse,
    UpsertTenantFlowScheduleRequest,
    UpdateTenantCredentialConfigRequest,
    WalletBalanceSummaryResponse,
    WalletBreakdownItemResponse,
    WalletDailyUsageItemResponse,
    WalletLedgerEntryResponse,
    WalletLedgerListResponse,
    ProviderMonitorCardResponse,
    ProviderMonitorLinkResponse,
    ProviderMonitorListResponse,
    WalletPeriodSummaryResponse,
    WorkflowRunListItemResponse,
    WorkflowRunListResponse,
    success_response,
)
from workflow.flow.registry import has_flow_definition
from workflow.flow.content_create.utils import extract_generation_reference_image_urls
from workflow.runtime.tenant import TenantRuntimeConfig
from workflow.runtime.engine import GraphRuntime, RunRequest
from workflow.runtime.scheduler import compute_next_run_at, normalize_batch_id_prefix, validate_cron_expression
from workflow.settings import WorkflowSettings
from workflow.integrations.image_generation import edit_image, generate_images
from workflow.core.env import env_value
from workflow.store.database import get_dataset_definition, get_table_dataset_definition, list_display_dataset_definitions
from workflow.store import StoreError


router = APIRouter()

_ENSURED_DATABASE_URLS: set[str] = set()
_ENSURE_DATABASE_LOCK = Lock()
_WALLET_SEED_CACHE_LOCK = Lock()
_WALLET_SEED_GUARDS: dict[str, Lock] = {}
_WALLET_SEEDED_TENANTS: set[str] = set()
_PROVIDER_MONITOR_CACHE_LOCK = Lock()
_PROVIDER_MONITOR_CACHE: dict[str, dict[str, Any]] = {}
PROVIDER_MONITOR_CACHE_TTL_SECONDS = 60.0
PROVIDER_MONITOR_STALE_TTL_SECONDS = 300.0
PROVIDER_MONITOR_REMOTE_TIMEOUT_SECONDS = 1.5
PRODUCT_TABLE_SUMMARY_MODE = "product_card"
PROVIDER_LLM = "llm"
PROVIDER_CONTENT_GENERATION = "content-generation"
PROVIDER_TIKHUB = "tikhub"
CHANNEL_COPYWRITING = "文案生成"
CHANNEL_IMAGE = "图片生成"
CHANNEL_DATA = "数据采集"
CHANNEL_MONITOR = "额度监控"


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat()


def build_schedule_response(schedule) -> TenantFlowScheduleResponse:
    return TenantFlowScheduleResponse(
        tenant_id=schedule.tenant_id,
        flow_id=schedule.flow_id,
        cron=schedule.cron_expr,
        is_active=schedule.is_active,
        batch_id_prefix=schedule.batch_id_prefix,
        request_payload=schedule.request_payload,
        next_run_at=_format_datetime(schedule.next_run_at),
        last_run_at=_format_datetime(schedule.last_run_at),
        last_status=schedule.last_status,
        last_error=schedule.last_error,
        last_batch_id=schedule.last_batch_id,
        is_running=schedule.is_running,
    )


def require_database(settings: WorkflowSettings) -> str:
    if not postgres_enabled(settings.database_url):
        raise HTTPException(status_code=400, detail="缺少 DATABASE_URL，当前未启用 PostgreSQL 配置")
    if settings.database_url not in _ENSURED_DATABASE_URLS:
        with _ENSURE_DATABASE_LOCK:
            if settings.database_url not in _ENSURED_DATABASE_URLS:
                ensure_postgres_tables(settings.database_url)
                _ENSURED_DATABASE_URLS.add(settings.database_url)
    return settings.database_url


def _resolve_tenant_id(explicit_tenant_id: str | None, authenticated_tenant_id: str) -> str:
    tenant_id = str(explicit_tenant_id or "").strip()
    return tenant_id or authenticated_tenant_id


def _build_table_row(entry) -> dict:
    row = {"record_id": entry.record_key}
    row.update(entry.payload if isinstance(entry.payload, dict) else {})
    return row


def _resolve_table_summary_mode(dataset_key: str, summary: bool) -> str:
    if summary and dataset_key == "products":
        return PRODUCT_TABLE_SUMMARY_MODE
    return "full"


def _build_workflow_run_item(entry) -> WorkflowRunListItemResponse:
    return WorkflowRunListItemResponse(
        tenant_id=entry.tenant_id,
        flow_id=entry.flow_id,
        batch_id=entry.batch_id,
        trigger_mode=entry.trigger_mode,
        source_url=entry.source_url,
        status=entry.status,
        current_node=entry.current_node,
        current_node_index=entry.current_node_index,
        total_node_count=entry.total_node_count,
        resume_count=entry.resume_count,
        completed_node_count=entry.completed_node_count,
        error_count=entry.error_count,
        last_message=entry.last_message,
        last_error=entry.last_error,
        started_at=_format_datetime(entry.started_at),
        updated_at=_format_datetime(entry.updated_at),
        finished_at=_format_datetime(entry.finished_at),
        run_path=f"/api/flows/{entry.flow_id}/runs/{entry.batch_id}",
    )


def _build_artifact_item(entry) -> ArtifactResponse:
    return ArtifactResponse(
        artifact_id=entry.id,
        tenant_id=entry.tenant_id,
        flow_id=entry.flow_id,
        batch_id=entry.batch_id,
        workflow_run_id=entry.workflow_run_id,
        artifact_type=entry.artifact_type,
        title=entry.title,
        content=entry.content,
        tags=entry.tags,
        cover_prompt=entry.cover_prompt,
        cover_url=entry.cover_url,
        image_prompts=entry.image_prompts,
        image_urls=entry.image_urls,
        source_url=entry.source_url,
        payload=entry.payload,
        created_at=_format_datetime(entry.created_at),
        updated_at=_format_datetime(entry.updated_at),
    )


def _build_wallet_entry_item(entry) -> WalletLedgerEntryResponse:
    return WalletLedgerEntryResponse(
        entry_id=entry.id,
        tenant_id=entry.tenant_id,
        entry_type=entry.entry_type,
        amount=entry.amount,
        title=entry.title,
        channel=entry.channel,
        provider=entry.provider,
        provider_event_id=entry.provider_event_id,
        related_resource_type=entry.related_resource_type,
        related_resource_id=entry.related_resource_id,
        status=entry.status,
        detail=entry.detail,
        metadata=entry.metadata,
        occurred_at=_format_datetime(entry.occurred_at),
        created_at=_format_datetime(entry.created_at),
        updated_at=_format_datetime(entry.updated_at),
    )


def _copy_artifact_payload(artifact) -> dict:
    return dict(artifact.payload) if isinstance(artifact.payload, dict) else {}


def _normalize_string_list(values: list[str] | None) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(item).strip() for item in values if str(item).strip()]


def _safe_json_request_json_verbose(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 2.5,
) -> tuple[dict[str, Any] | list[Any] | None, str]:
    request = Request(url, headers=headers or {}, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:
            detail = ""
        message = f"HTTP {exc.code}"
        if detail:
            message = f"{message}: {detail[:180]}"
        return None, message
    except URLError as exc:
        return None, str(exc)
    except (TimeoutError, ValueError) as exc:
        return None, str(exc)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None, "invalid json response"
    return (payload if isinstance(payload, (dict, list)) else None), ""



def _build_provider_monitor_link(label: str, url: str) -> ProviderMonitorLinkResponse:
    return ProviderMonitorLinkResponse(label=label, url=str(url or "").strip())


def _coerce_monitor_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            return float(normalized)
        except ValueError:
            return None
    return None


def _monitor_balance_payload_amount(payload: dict[str, Any] | None) -> float | None:
    if not isinstance(payload, dict):
        return None
    return _coerce_monitor_float(payload.get("remote_balance"))


def _sync_provider_monitor_balance_delta(
    *,
    database_url: str,
    tenant_id: str,
    provider: str,
    balance: float | None,
    balance_unit: str,
    occurred_at: datetime,
) -> dict[str, Any]:
    if balance is None:
        return {
            "has_previous_balance": False,
            "delta_amount": 0.0,
        }

    latest_events, _ = list_provider_usage_events(
        database_url,
        tenant_id=tenant_id,
        provider=provider,
        channel=CHANNEL_MONITOR,
        limit=1,
        offset=0,
    )
    latest_event = latest_events[0] if latest_events else None
    previous_balance = _monitor_balance_payload_amount(latest_event.payload if latest_event is not None else None)
    has_previous_balance = previous_balance is not None
    delta_amount = round(max(0.0, previous_balance - balance), 4) if has_previous_balance else 0.0
    event_suffix = occurred_at.isoformat(timespec="microseconds")

    create_provider_usage_event(
        database_url,
        tenant_id=tenant_id,
        provider=provider,
        provider_event_id=f"provider-monitor:{provider}:{event_suffix}",
        request_id=f"provider-monitor:{provider}:{event_suffix}",
        channel=CHANNEL_MONITOR,
        feature_key="provider-monitor-balance-sync",
        amount=delta_amount,
        currency=str(balance_unit or "CNY").strip() or "CNY",
        related_resource_type="provider_monitor",
        related_resource_id=provider,
        status="completed" if delta_amount > 0 else "recorded",
        payload={
            "remote_balance": round(float(balance), 6),
            "remote_balance_unit": str(balance_unit or "CNY").strip() or "CNY",
            "price_source": "remote_balance_delta",
        },
        occurred_at=occurred_at,
    )
    return {
        "has_previous_balance": has_previous_balance,
        "delta_amount": delta_amount,
    }


def _fetch_rightcode_account_summary(
    api_key: str,
    *,
    timeout: float = 2.5,
) -> tuple[dict[str, Any] | list[Any] | None, str]:
    return _safe_json_request_json_verbose(
        "https://www.right.codes/account/summary",
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "cc-switch/1.0",
        },
        timeout=timeout,
    )


def _get_runtime_api_value(
    runtime_payload: dict[str, Any] | None,
    key: str,
    *,
    settings: WorkflowSettings,
    fallback: str = "",
    allow_env_fallback: bool = True,
) -> str:
    if isinstance(runtime_payload, dict):
        api_ref = runtime_payload.get("api_ref")
        if isinstance(api_ref, dict):
            value = str(api_ref.get(key) or "").strip()
            if value:
                return value
    if allow_env_fallback:
        env_config = str(env_value(key, settings.root) or "").strip()
        if env_config:
            return env_config
    return fallback


def _build_provider_monitor_cards(
    *,
    settings: WorkflowSettings,
    tenant_id: str,
    runtime_payload: dict[str, Any] | None,
    database_url: str,
) -> list[ProviderMonitorCardResponse]:
    now = datetime.now()
    today = now.date().isoformat()
    week_start = (now - timedelta(days=6)).date().isoformat()
    month_start = (now - timedelta(days=29)).date().isoformat()

    hydrate_provider_usage_from_ledger(database_url, tenant_id=tenant_id)

    llm_base_url = _get_runtime_api_value(runtime_payload, "OPENAI_BASE_URL", settings=settings, fallback="https://right.codes/gemini/v1")
    image_base_url = _get_runtime_api_value(
        runtime_payload,
        "OPENAI_IMAGE_BASE_URL",
        settings=settings,
        fallback=llm_base_url,
    )
    llm_model = _get_runtime_api_value(runtime_payload, "OPENAI_MODEL", settings=settings, fallback="")
    llm_api_key = _get_runtime_api_value(
        runtime_payload,
        "OPENAI_API_KEY",
        settings=settings,
        allow_env_fallback=False,
    )
    tikhub_api_key = _get_runtime_api_value(
        runtime_payload,
        "TIKHUB_API_KEY",
        settings=settings,
        allow_env_fallback=False,
    )

    tikhub_balance = None
    tikhub_status = "warning"
    tikhub_note = ""
    if tikhub_api_key:
        tikhub_payload, tikhub_error = _safe_json_request_json_verbose(
            "https://api.tikhub.io/api/v1/tikhub/user/get_user_info",
            headers={
                "Authorization": f"Bearer {tikhub_api_key}",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0",
            },
            timeout=PROVIDER_MONITOR_REMOTE_TIMEOUT_SECONDS,
        )
        if isinstance(tikhub_payload, dict):
            user_data = tikhub_payload.get("user_data")
            if isinstance(user_data, dict):
                parsed_balance = _coerce_monitor_float(user_data.get("balance"))
                if parsed_balance is not None:
                    tikhub_balance = parsed_balance
                    tikhub_status = "healthy"
                    tikhub_note = ""
                else:
                    tikhub_status = "warning"
                    tikhub_note = "余额字段缺失"
        else:
            tikhub_status = "warning"
            tikhub_note = "余额查询失败"

    llm_balance = None
    llm_balance_unit = "CNY"
    llm_status = "warning"
    llm_note = "请先在当前空间填写图文生成 API Key"
    if llm_api_key and "right.codes" in image_base_url.lower():
        llm_payload, llm_error = _fetch_rightcode_account_summary(
            llm_api_key,
            timeout=PROVIDER_MONITOR_REMOTE_TIMEOUT_SECONDS,
        )
        if isinstance(llm_payload, dict):
            parsed_balance = _coerce_monitor_float(llm_payload.get("balance"))
            if parsed_balance is not None:
                llm_balance = parsed_balance
                llm_balance_unit = "USD"
                llm_status = "healthy"
                llm_note = ""
            else:
                llm_status = "warning"
                llm_note = "余额字段缺失"
        elif llm_error:
            llm_status = "warning"
            llm_note = "余额查询失败"
    elif llm_api_key:
        llm_status = "info"
        llm_note = "当前空间已保存图文生成 Key，但当前图片链路暂不支持余额监控"

    content_generation_sync = _sync_provider_monitor_balance_delta(
        database_url=database_url,
        tenant_id=tenant_id,
        provider=PROVIDER_CONTENT_GENERATION,
        balance=llm_balance,
        balance_unit=llm_balance_unit,
        occurred_at=now,
    )
    tikhub_sync = _sync_provider_monitor_balance_delta(
        database_url=database_url,
        tenant_id=tenant_id,
        provider=PROVIDER_TIKHUB,
        balance=tikhub_balance,
        balance_unit="CNY",
        occurred_at=now,
    )

    provider_usage_rollups = summarize_provider_usage_windows(
        database_url,
        tenant_id=tenant_id,
        provider_channels=[
            (PROVIDER_LLM, CHANNEL_COPYWRITING),
            ("openai", CHANNEL_IMAGE),
            (PROVIDER_TIKHUB, CHANNEL_DATA),
            (PROVIDER_CONTENT_GENERATION, CHANNEL_MONITOR),
            (PROVIDER_TIKHUB, CHANNEL_MONITOR),
        ],
        today_from=today,
        week_from=week_start,
        month_from=month_start,
    )

    llm_usage = provider_usage_rollups.get((PROVIDER_LLM, CHANNEL_COPYWRITING), {"today": 0.0, "week": 0.0, "month": 0.0})
    openai_image_usage = provider_usage_rollups.get(("openai", CHANNEL_IMAGE), {"today": 0.0, "week": 0.0, "month": 0.0})
    tikhub_usage = provider_usage_rollups.get((PROVIDER_TIKHUB, CHANNEL_DATA), {"today": 0.0, "week": 0.0, "month": 0.0})
    content_generation_monitor_usage = provider_usage_rollups.get(
        (PROVIDER_CONTENT_GENERATION, CHANNEL_MONITOR),
        {"today": 0.0, "week": 0.0, "month": 0.0, "last_synced_at": None},
    )
    tikhub_monitor_usage = provider_usage_rollups.get(
        (PROVIDER_TIKHUB, CHANNEL_MONITOR),
        {"today": 0.0, "week": 0.0, "month": 0.0, "last_synced_at": None},
    )

    provider_usage_summary = {
        PROVIDER_CONTENT_GENERATION: (
            {
                "today": float(content_generation_monitor_usage["today"]),
                "week": float(content_generation_monitor_usage["week"]),
                "month": float(content_generation_monitor_usage["month"]),
            }
            if content_generation_sync["has_previous_balance"]
            else {
                "today": float(llm_usage["today"]) + float(openai_image_usage["today"]),
                "week": float(llm_usage["week"]) + float(openai_image_usage["week"]),
                "month": float(llm_usage["month"]) + float(openai_image_usage["month"]),
            }
        ),
        PROVIDER_TIKHUB: (
            {
                "today": float(tikhub_monitor_usage["today"]),
                "week": float(tikhub_monitor_usage["week"]),
                "month": float(tikhub_monitor_usage["month"]),
            }
            if tikhub_sync["has_previous_balance"]
            else {
                "today": float(tikhub_usage["today"]),
                "week": float(tikhub_usage["week"]),
                "month": float(tikhub_usage["month"]),
            }
        ),
    }

    provider_usage_last_synced = {
        PROVIDER_CONTENT_GENERATION: (
            content_generation_monitor_usage.get("last_synced_at")
            if content_generation_sync["has_previous_balance"]
            else provider_usage_rollups.get((PROVIDER_LLM, CHANNEL_COPYWRITING), {}).get("last_synced_at")
            or provider_usage_rollups.get(("openai", CHANNEL_IMAGE), {}).get("last_synced_at")
        ),
        PROVIDER_TIKHUB: (
            tikhub_monitor_usage.get("last_synced_at")
            if tikhub_sync["has_previous_balance"]
            else provider_usage_rollups.get((PROVIDER_TIKHUB, CHANNEL_DATA), {}).get("last_synced_at")
        ),
    }

    content_generation_balance = llm_balance
    content_generation_balance_unit = llm_balance_unit
    content_generation_status = llm_status
    content_generation_note = llm_note

    return [
        ProviderMonitorCardResponse(
            provider_key=PROVIDER_CONTENT_GENERATION,
            provider_name="图文生成",
            category="Platform",
            status=content_generation_status,
            balance=content_generation_balance,
            balance_unit=content_generation_balance_unit,
            today_usage=provider_usage_summary[PROVIDER_CONTENT_GENERATION]["today"],
            week_usage=provider_usage_summary[PROVIDER_CONTENT_GENERATION]["week"],
            month_usage=provider_usage_summary[PROVIDER_CONTENT_GENERATION]["month"],
            last_synced_at=_format_datetime(provider_usage_last_synced[PROVIDER_CONTENT_GENERATION]),
            note=content_generation_note,
            recharge_link=_build_provider_monitor_link("前往充值", settings.llm_recharge_url),
            console_link=_build_provider_monitor_link("控制台", settings.llm_console_url),
            log_link=_build_provider_monitor_link("日志", settings.llm_log_url),
        ),
        ProviderMonitorCardResponse(
            provider_key=PROVIDER_TIKHUB,
            provider_name="数据采集",
            category="Data",
            status=tikhub_status,
            balance=tikhub_balance,
            balance_unit="CNY",
            today_usage=provider_usage_summary[PROVIDER_TIKHUB]["today"],
            week_usage=provider_usage_summary[PROVIDER_TIKHUB]["week"],
            month_usage=provider_usage_summary[PROVIDER_TIKHUB]["month"],
            last_synced_at=_format_datetime(provider_usage_last_synced[PROVIDER_TIKHUB]),
            note=tikhub_note,
            recharge_link=_build_provider_monitor_link("前往充值", settings.tikhub_recharge_url),
            console_link=_build_provider_monitor_link("控制台", settings.tikhub_console_url),
            log_link=_build_provider_monitor_link("日志", settings.tikhub_log_url),
        ),
    ]


def _provider_monitor_cache_key(database_url: str, tenant_id: str) -> str:
    return f"{database_url}\0{tenant_id}"


def _get_cached_provider_monitor_payload(cache_key: str) -> tuple[dict[str, Any] | None, bool]:
    with _PROVIDER_MONITOR_CACHE_LOCK:
        cached = _PROVIDER_MONITOR_CACHE.get(cache_key)
    if not isinstance(cached, dict):
        return None, False

    payload = cached.get("payload")
    expires_at = float(cached.get("expires_at") or 0.0)
    stale_until = float(cached.get("stale_until") or 0.0)
    now = monotonic()
    if isinstance(payload, dict) and expires_at > now:
        return payload, True
    if isinstance(payload, dict) and stale_until > now:
        return payload, False
    return None, False


def _provider_monitor_payload_has_failure(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    providers = payload.get("providers")
    if not isinstance(providers, list):
        return False
    for item in providers:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        note = str(item.get("note") or "").strip()
        balance = item.get("balance")
        if status == "warning" and ("查询失败" in note or note == "余额查询失败" or balance is None):
            return True
    return False


def _store_provider_monitor_payload(cache_key: str, payload: dict[str, Any]) -> None:
    now = monotonic()
    with _PROVIDER_MONITOR_CACHE_LOCK:
        _PROVIDER_MONITOR_CACHE[cache_key] = {
            "payload": payload,
            "expires_at": now + PROVIDER_MONITOR_CACHE_TTL_SECONDS,
            "stale_until": now + PROVIDER_MONITOR_STALE_TTL_SECONDS,
        }


def _clear_provider_monitor_cache(database_url: str, tenant_id: str) -> None:
    cache_key = _provider_monitor_cache_key(database_url, tenant_id)
    with _PROVIDER_MONITOR_CACHE_LOCK:
        _PROVIDER_MONITOR_CACHE.pop(cache_key, None)


def _build_provider_monitor_payload(
    *,
    settings: WorkflowSettings,
    tenant_id: str,
    runtime_payload: dict[str, Any] | None,
    database_url: str,
) -> dict[str, Any]:
    return ProviderMonitorListResponse(
        tenant_id=tenant_id,
        updated_at=_format_datetime(datetime.now()),
        providers=_build_provider_monitor_cards(
            settings=settings,
            tenant_id=tenant_id,
            runtime_payload=runtime_payload,
            database_url=database_url,
        ),
    ).model_dump()


def _wallet_seed_cache_key(database_url: str, tenant_id: str) -> str:
    return f"{database_url}\0{tenant_id}"


def _ensure_wallet_seed_data(database_url: str, tenant_id: str) -> None:
    cache_key = _wallet_seed_cache_key(database_url, tenant_id)
    with _WALLET_SEED_CACHE_LOCK:
        if cache_key in _WALLET_SEEDED_TENANTS:
            return
        guard = _WALLET_SEED_GUARDS.get(cache_key)
        if guard is None:
            guard = Lock()
            _WALLET_SEED_GUARDS[cache_key] = guard

    with guard:
        with _WALLET_SEED_CACHE_LOCK:
            if cache_key in _WALLET_SEEDED_TENANTS:
                return

        ensure_tenant_wallet(database_url, tenant_id=tenant_id)
        hydrate_provider_usage_from_ledger(database_url, tenant_id=tenant_id)
        existing_entries, total = list_wallet_ledger_entries(
            database_url,
            tenant_id=tenant_id,
            limit=1,
            offset=0,
        )
        if total > 0 or existing_entries:
            with _WALLET_SEED_CACHE_LOCK:
                _WALLET_SEEDED_TENANTS.add(cache_key)
                _WALLET_SEED_GUARDS.pop(cache_key, None)
            return

        now = datetime.now()
        seed_entries = [
            {
                "entry_type": "recharge",
                "amount": 500.0,
                "title": "账户充值",
                "channel": "额度管理",
                "provider": "manual",
                "provider_event_id": f"{tenant_id}-recharge-001",
                "status": "completed",
                "detail": "初始化演示充值记录",
                "metadata": {"method": "线下转账"},
                "occurred_at": now - timedelta(days=6, hours=3),
            },
            {
                "entry_type": "consume",
                "amount": -18.6,
                "title": "行业报告生成",
                "channel": "策略生成",
                "provider": "system",
                "provider_event_id": f"{tenant_id}-consume-001",
                "status": "completed",
                "detail": "初始化行业报告生成消耗",
                "related_resource_type": "flow",
                "related_resource_id": "content-collect",
                "metadata": {"feature": "industry-report"},
                "occurred_at": now - timedelta(days=5, hours=4),
            },
            {
                "entry_type": "consume",
                "amount": -0.12,
                "title": "对标二创抓取",
                "channel": "数据采集",
                "provider": "tikhub",
                "provider_event_id": f"{tenant_id}-consume-002",
                "status": "completed",
                "detail": "初始化对标二创抓取消耗",
                "related_resource_type": "flow",
                "related_resource_id": "content-create-rewrite",
                "metadata": {"feature": "rewrite-fetch"},
                "occurred_at": now - timedelta(days=4, hours=2),
            },
            {
                "entry_type": "consume",
                "amount": -12.8,
                "title": "产品图片生成",
                "channel": "图片生成",
                "provider": "openai",
                "provider_event_id": f"{tenant_id}-consume-003",
                "status": "completed",
                "detail": "初始化产品图片生成消耗",
                "related_resource_type": "artifact",
                "related_resource_id": "seed-artifact-1",
                "metadata": {"feature": "product-generate"},
                "occurred_at": now - timedelta(days=3, hours=1),
            },
            {
                "entry_type": "recharge",
                "amount": 200.0,
                "title": "手动充值",
                "channel": "额度管理",
                "provider": "manual",
                "provider_event_id": f"{tenant_id}-recharge-002",
                "status": "completed",
                "detail": "补充演示充值记录",
                "metadata": {"method": "支付宝"},
                "occurred_at": now - timedelta(days=2, hours=5),
            },
            {
                "entry_type": "consume",
                "amount": -7.21,
                "title": "今日日报",
                "channel": "日报生成",
                "provider": "system",
                "provider_event_id": f"{tenant_id}-consume-004",
                "status": "completed",
                "detail": "初始化今日日报生成消耗",
                "related_resource_type": "flow",
                "related_resource_id": "daily-report",
                "metadata": {"feature": "daily-report"},
                "occurred_at": now - timedelta(days=1, hours=4),
            },
            {
                "entry_type": "consume",
                "amount": -4.35,
                "title": "图片重绘",
                "channel": "图片生成",
                "provider": "openai",
                "provider_event_id": f"{tenant_id}-consume-005",
                "status": "completed",
                "detail": "初始化作品图片重绘消耗",
                "related_resource_type": "artifact",
                "related_resource_id": "seed-artifact-2",
                "metadata": {"feature": "image-regenerate"},
                "occurred_at": now - timedelta(hours=10),
            },
        ]

        for item in seed_entries:
            entry = create_wallet_ledger_entry(
                database_url,
                tenant_id=tenant_id,
                entry_type=str(item["entry_type"]),
                amount=float(item["amount"]),
                title=str(item["title"]),
                channel=str(item["channel"]),
                provider=str(item.get("provider") or ""),
                provider_event_id=str(item.get("provider_event_id") or ""),
                related_resource_type=str(item.get("related_resource_type") or ""),
                related_resource_id=str(item.get("related_resource_id") or ""),
                status=str(item.get("status") or "completed"),
                detail=str(item.get("detail") or ""),
                metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                occurred_at=item.get("occurred_at"),
            )
            if str(item["entry_type"]) == "consume" and str(item.get("provider") or "").strip():
                create_provider_usage_event(
                    database_url,
                    tenant_id=tenant_id,
                    provider=str(item.get("provider") or ""),
                    provider_event_id=str(item.get("provider_event_id") or ""),
                    channel=str(item.get("channel") or ""),
                    feature_key=str((item.get("metadata") or {}).get("feature") or ""),
                    model_name=str((item.get("metadata") or {}).get("model_name") or ""),
                    amount=abs(float(item["amount"])),
                    related_resource_type=str(item.get("related_resource_type") or ""),
                    related_resource_id=str(item.get("related_resource_id") or ""),
                    ledger_entry_id=entry.id,
                    status=str(item.get("status") or "completed"),
                    payload=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                    occurred_at=item.get("occurred_at"),
                )
        sync_tenant_wallet_balance(database_url, tenant_id=tenant_id)

        with _WALLET_SEED_CACHE_LOCK:
            _WALLET_SEEDED_TENANTS.add(cache_key)
            _WALLET_SEED_GUARDS.pop(cache_key, None)


def _merge_artifact_payload(
    artifact,
    *,
    title: str,
    content: str,
    tags: str,
    cover_prompt: str,
    image_prompts: list[str],
    cover_url: str,
    image_urls: list[str],
) -> dict:
    payload = _copy_artifact_payload(artifact)
    copy_payload = payload.get("copy")
    prompt_payload = payload.get("prompts")
    image_payload = payload.get("images")

    payload["copy"] = {
        **(copy_payload if isinstance(copy_payload, dict) else {}),
        "title": title,
        "content": content,
        "tags": tags,
    }
    payload["prompts"] = {
        **(prompt_payload if isinstance(prompt_payload, dict) else {}),
        "cover_prompt": cover_prompt,
        "image_prompts": image_prompts,
    }
    payload["images"] = {
        **(image_payload if isinstance(image_payload, dict) else {}),
        "cover_url": cover_url,
        "image_urls": image_urls,
    }
    return payload


def _artifact_topic_context(artifact) -> dict[str, Any]:
    payload = _copy_artifact_payload(artifact)
    topic_context = payload.get("topic_context")
    return topic_context if isinstance(topic_context, dict) else {}


def _build_artifact_edit_reference_images(artifact, selected_image_url: str) -> list[str]:
    topic_context = _artifact_topic_context(artifact)
    generation_reference_images = extract_generation_reference_image_urls(topic_context)

    ordered: list[str] = []
    seen: set[str] = set()
    for value in [selected_image_url, *generation_reference_images, artifact.cover_url, *list(artifact.image_urls)]:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered[:8]


def _generate_artifact_image_edit_preview(
    artifact,
    *,
    image_index: int,
    prompt: str | None,
    settings: WorkflowSettings,
    tenant_config: dict,
    topic_context: dict[str, Any] | None = None,
    billing_context: dict[str, Any] | None = None,
) -> dict:
    prompt_override = str(prompt or "").strip()
    current_image_prompts = list(artifact.image_prompts)
    current_image_urls = list(artifact.image_urls)

    if image_index == 0:
        next_prompt = prompt_override or str(artifact.cover_prompt or "").strip()
        selected_image_url = str(artifact.cover_url or "").strip()
        if not next_prompt:
            raise HTTPException(status_code=400, detail="cover prompt is empty")
    else:
        image_prompt_index = image_index - 1
        slot_count = max(len(current_image_prompts), len(current_image_urls))
        if image_prompt_index >= slot_count:
            raise HTTPException(status_code=400, detail="image_index out of range")
        while len(current_image_prompts) <= image_prompt_index:
            current_image_prompts.append("")
        while len(current_image_urls) <= image_prompt_index:
            current_image_urls.append("")
        next_prompt = prompt_override or str(current_image_prompts[image_prompt_index] or "").strip()
        selected_image_url = str(current_image_urls[image_prompt_index] or "").strip()
        if not next_prompt:
            raise HTTPException(status_code=400, detail="selected image prompt is empty")

    reference_image_urls = _build_artifact_edit_reference_images(artifact, selected_image_url)
    if not reference_image_urls:
        raise HTTPException(status_code=400, detail="no reference images available for image edit")

    try:
        image_payload = edit_image(
            {
                "root": str(settings.root),
                "step": {},
                "batch_id": f"{artifact.batch_id or artifact.id}-edit-{image_index}",
                "tenant_config": TenantRuntimeConfig(payload=tenant_config),
            },
            next_prompt,
            reference_image_urls,
            billing_context=billing_context,
        )
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    generated_url = str(image_payload.get("cover_url") or "").strip()
    if not generated_url:
        raise HTTPException(status_code=502, detail="image generation did not return a URL")

    return {
        "artifact_id": artifact.id,
        "image_index": image_index,
        "prompt": next_prompt,
        "generated_url": generated_url,
        "reference_image_urls": reference_image_urls,
        "image_payload": image_payload,
    }


def _require_table_dataset(dataset_key: str):
    dataset = get_table_dataset_definition(dataset_key)
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"unknown table dataset: {dataset_key}")
    return dataset


def _require_display_dataset(dataset_key: str):
    dataset = get_dataset_definition(dataset_key)
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"unknown dataset: {dataset_key}")
    return dataset


def _dataset_fields(dataset) -> list[str]:
    if dataset.kind == "doc":
        return ["文档"]
    return list(dataset.fields)


def _build_doc_row(entry) -> dict:
    return {
        "record_id": entry.record_key or "__doc__",
        "文档": entry.content_text,
    }


@router.get("/health")
def health() -> dict:
    return success_response({"status": "ok"})


@router.get("/tenants")
def get_tenants(
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
) -> dict:
    database_url = require_database(settings)
    tenants = list_tenants(database_url)
    data = {
        "tenants": [
            TenantResponse(
                tenant_id=item.tenant_id,
                tenant_name=item.tenant_name,
                api_key=item.api_key,
                is_active=item.is_active,
                default_llm_model=item.default_llm_model,
                api_mode=item.api_mode,
                api_ref=item.api_ref,
                timeout_seconds=item.timeout_seconds,
                max_retries=item.max_retries,
            )
            for item in tenants
        ]
    }
    return success_response(data)


@router.post("/spaces/lookup")
def lookup_space(
    request: ResolveSpaceRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
) -> dict:
    database_url = require_database(settings)
    tenant = get_tenant_by_api_key(database_url, request.api_key)
    if tenant is None:
        return success_response(ResolveSpaceResponse(registered=False).model_dump())
    return success_response(
        ResolveSpaceResponse(
            registered=True,
            tenant_id=tenant.tenant_id,
            tenant_name=tenant.tenant_name,
        ).model_dump()
    )


@router.post("/tenants")
def create_tenant(
    request: CreateTenantRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
) -> dict:
    database_url = require_database(settings)
    normalized_api_key = request.api_key.strip()
    existing_tenant = get_tenant_by_api_key(database_url, normalized_api_key)
    if existing_tenant is not None:
        raise HTTPException(status_code=409, detail="api key already registered")
    tenant = upsert_tenant(
        database_url,
        tenant_id=generate_tenant_id(database_url, request.tenant_name),
        tenant_name=request.tenant_name,
        api_key=normalized_api_key,
        is_active=request.is_active,
        default_llm_model=request.default_llm_model,
        api_mode=request.api_mode,
        api_ref=request.api_ref if request.api_mode == "custom" else {},
        timeout_seconds=request.timeout_seconds,
        max_retries=request.max_retries,
    )
    return success_response(
        TenantResponse(
            tenant_id=tenant.tenant_id,
            tenant_name=tenant.tenant_name,
            api_key=tenant.api_key,
            is_active=tenant.is_active,
            default_llm_model=tenant.default_llm_model,
            api_mode=tenant.api_mode,
            api_ref=tenant.api_ref,
            timeout_seconds=tenant.timeout_seconds,
            max_retries=tenant.max_retries,
        ).model_dump()
    )


@router.get("/account/credentials")
def get_account_credentials(
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(None, authenticated_tenant_id)
    database_url = require_database(settings)
    tenant = get_tenant_by_id(database_url, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    return success_response(
        TenantCredentialConfigResponse(
            tenant_id=tenant.tenant_id,
            tenant_name=tenant.tenant_name,
            api_mode=tenant.api_mode,
            default_llm_model=tenant.default_llm_model,
            timeout_seconds=tenant.timeout_seconds,
            max_retries=tenant.max_retries,
            api_ref=tenant.api_ref,
        ).model_dump()
    )


@router.put("/account/credentials")
def update_account_credentials(
    request: UpdateTenantCredentialConfigRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(None, authenticated_tenant_id)
    database_url = require_database(settings)
    tenant = get_tenant_by_id(database_url, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")

    normalized_api_ref = request.api_ref if request.api_mode == "custom" else {}
    updated = upsert_tenant(
        database_url,
        tenant_id=tenant.tenant_id,
        tenant_name=tenant.tenant_name,
        api_key=tenant.api_key,
        is_active=tenant.is_active,
        default_llm_model=request.default_llm_model,
        api_mode=request.api_mode,
        api_ref=normalized_api_ref,
        timeout_seconds=request.timeout_seconds,
        max_retries=request.max_retries,
    )
    _clear_provider_monitor_cache(database_url, tenant_id)
    return success_response(
        TenantCredentialConfigResponse(
            tenant_id=updated.tenant_id,
            tenant_name=updated.tenant_name,
            api_mode=updated.api_mode,
            default_llm_model=updated.default_llm_model,
            timeout_seconds=updated.timeout_seconds,
            max_retries=updated.max_retries,
            api_ref=updated.api_ref,
        ).model_dump()
    )


def get_tenant_schedules(
    tenant_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    database_url = require_database(settings)
    schedules = list_tenant_flow_schedules(database_url, tenant_id)
    return success_response(
        TenantFlowScheduleListResponse(
            schedules=[build_schedule_response(item) for item in schedules],
        ).model_dump()
    )


def list_tenant_tables(
    tenant_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    database_url = require_database(settings)
    tables = [
        DatasetTableCatalogItemResponse(
            dataset_key=dataset.dataset_key,
            dataset_name=dataset.name,
            fields=_dataset_fields(dataset),
        )
        for dataset in list_display_dataset_definitions()
    ]
    return success_response(DatasetTableCatalogResponse(tables=tables).model_dump())


def get_tenant_table_rows(
    tenant_id: str,
    dataset_key: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
    limit: int | None = None,
    offset: int = 0,
    order: str = "asc",
    summary: bool = False,
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    database_url = require_database(settings)
    dataset = _require_display_dataset(dataset_key)
    summary_mode = _resolve_table_summary_mode(dataset.dataset_key, summary)
    if dataset.kind == "doc":
        entries = list_store_entries(
            database_url,
            tenant_id=tenant_id,
            dataset_key=dataset.dataset_key,
            entry_type="doc",
            limit=limit,
            offset=offset,
            order=order,
            summary_mode=summary_mode,
        )
        response = DatasetTableListResponse(
            tenant_id=tenant_id,
            dataset_key=dataset.dataset_key,
            dataset_name=dataset.name,
            fields=_dataset_fields(dataset),
            rows=[_build_doc_row(entry) for entry in entries],
        )
        return success_response(response.model_dump())

    entries = list_store_entries(
        database_url,
        tenant_id=tenant_id,
        dataset_key=dataset.dataset_key,
        entry_type="row",
        limit=limit,
        offset=offset,
        order=order,
        summary_mode=summary_mode,
    )
    response = DatasetTableListResponse(
        tenant_id=tenant_id,
        dataset_key=dataset.dataset_key,
        dataset_name=dataset.name,
        fields=list(dataset.fields),
        rows=[_build_table_row(entry) for entry in entries],
    )
    return success_response(response.model_dump())


def get_tenant_table_row(
    tenant_id: str,
    dataset_key: str,
    record_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    database_url = require_database(settings)
    dataset = _require_table_dataset(dataset_key)
    entry = get_store_entry(
        database_url,
        tenant_id=tenant_id,
        dataset_key=dataset.dataset_key,
        entry_type="row",
        record_key=record_id,
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="table row not found")
    response = DatasetTableRowResponse(
        tenant_id=tenant_id,
        dataset_key=dataset.dataset_key,
        dataset_name=dataset.name,
        row=_build_table_row(entry),
    )
    return success_response(response.model_dump())


def create_tenant_table_row(
    tenant_id: str,
    dataset_key: str,
    request: DatasetTableRowRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    database_url = require_database(settings)
    dataset = _require_table_dataset(dataset_key)
    payload = dict(request.payload)
    if request.record_id.strip():
        payload["record_id"] = request.record_id.strip()
    inserted = insert_store_rows(
        database_url,
        tenant_id=tenant_id,
        dataset_key=dataset.dataset_key,
        rows=[payload],
    )
    if not inserted:
        raise HTTPException(status_code=400, detail="failed to create table row")
    response = DatasetTableRowResponse(
        tenant_id=tenant_id,
        dataset_key=dataset.dataset_key,
        dataset_name=dataset.name,
        row=_build_table_row(inserted[0]),
    )
    return success_response(response.model_dump())


def update_tenant_table_row(
    tenant_id: str,
    dataset_key: str,
    record_id: str,
    request: DatasetTableRowRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    database_url = require_database(settings)
    dataset = _require_table_dataset(dataset_key)
    existing_entry = get_store_entry(
        database_url,
        tenant_id=tenant_id,
        dataset_key=dataset.dataset_key,
        entry_type="row",
        record_key=record_id,
    )
    if existing_entry is None:
        raise HTTPException(status_code=404, detail="table row not found")
    payload = dict(existing_entry.payload) if isinstance(existing_entry.payload, dict) else {}
    payload.update(dict(request.payload))
    payload["record_id"] = record_id
    updated = update_store_rows(
        database_url,
        tenant_id=tenant_id,
        dataset_key=dataset.dataset_key,
        rows=[payload],
    )
    if not updated:
        raise HTTPException(status_code=400, detail="failed to update table row")
    response = DatasetTableRowResponse(
        tenant_id=tenant_id,
        dataset_key=dataset.dataset_key,
        dataset_name=dataset.name,
        row=_build_table_row(updated[0]),
    )
    return success_response(response.model_dump())


def delete_tenant_table_row(
    tenant_id: str,
    dataset_key: str,
    record_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    database_url = require_database(settings)
    dataset = _require_table_dataset(dataset_key)
    deleted = soft_delete_store_entry(
        database_url,
        tenant_id=tenant_id,
        dataset_key=dataset.dataset_key,
        entry_type="row",
        record_key=record_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="table row not found")
    return success_response(
        {
            "tenant_id": tenant_id,
            "dataset_key": dataset.dataset_key,
            "record_id": record_id,
            "deleted": True,
        }
    )


def get_tenant_schedule(
    tenant_id: str,
    flow_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    database_url = require_database(settings)
    schedule = get_tenant_flow_schedule(database_url, tenant_id, flow_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="tenant flow schedule not found")
    return success_response(build_schedule_response(schedule).model_dump())


def put_tenant_schedule(
    tenant_id: str,
    flow_id: str,
    request: UpsertTenantFlowScheduleRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    database_url = require_database(settings)
    tenant = get_tenant_by_id(database_url, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    if not has_flow_definition(flow_id):
        raise HTTPException(status_code=404, detail=f"unknown flow: {flow_id}")
    validate_cron_expression(request.cron)
    next_run_at = compute_next_run_at(request.cron) if request.is_active else None
    request_payload = request.request_payload.model_dump(exclude_defaults=True, exclude_none=True)
    schedule = upsert_tenant_flow_schedule(
        database_url,
        tenant_pk=tenant.id,
        tenant_id=tenant_id,
        flow_id=flow_id,
        cron_expr=request.cron,
        is_active=request.is_active,
        request_payload=request_payload,
        batch_id_prefix=normalize_batch_id_prefix(request.batch_id_prefix),
        next_run_at=next_run_at,
    )
    return success_response(build_schedule_response(schedule).model_dump())


def delete_tenant_schedule(
    tenant_id: str,
    flow_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    database_url = require_database(settings)
    deleted = delete_tenant_flow_schedule(database_url, tenant_id, flow_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="tenant flow schedule not found")
    return success_response({"tenant_id": tenant_id, "flow_id": flow_id, "deleted": True})


def trigger_tenant_schedule(
    tenant_id: str,
    flow_id: str,
    runtime: Annotated[GraphRuntime, Depends(get_runtime)],
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    try:
        tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
        database_url = require_database(settings)
        schedule = get_tenant_flow_schedule(database_url, tenant_id, flow_id)
        if schedule is None:
            raise HTTPException(status_code=404, detail="tenant flow schedule not found")
        runtime_payload = get_tenant_runtime_config(database_url, tenant_id)
        if runtime_payload is None:
            raise HTTPException(status_code=400, detail=f"PostgreSQL 中未找到 tenant_id={tenant_id} 的运行配置")
        request_payload = schedule.request_payload if isinstance(schedule.request_payload, dict) else {}
        result = runtime.run(
            RunRequest(
                flow_id=flow_id,
                tenant_id=tenant_id,
                trigger_mode="manual",
                source_url=str(request_payload.get("source_url") or ""),
                topic_context=request_payload.get("topic_context") if isinstance(request_payload.get("topic_context"), dict) else {},
                additional_instruction=str(request_payload.get("additional_instruction") or ""),
                image_additional_instruction=str(request_payload.get("image_additional_instruction") or ""),
                tenant_runtime_config=TenantRuntimeConfig(payload=runtime_payload),
            )
        )
        return success_response(result)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/flows")
def list_flows(
    runtime: Annotated[GraphRuntime, Depends(get_runtime)],
    _: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return success_response({"flows": runtime.list_flows()})


@router.post("/flows/{flow_id}/runs")
def run_flow(
    flow_id: str,
    request: RunFlowRequest,
    runtime: Annotated[GraphRuntime, Depends(get_runtime)],
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    try:
        tenant_id = _resolve_tenant_id(request.tenant_id, authenticated_tenant_id)
        database_url = require_database(settings)
        runtime_payload = get_tenant_runtime_config(database_url, tenant_id)
        if runtime_payload is None:
            raise HTTPException(status_code=400, detail=f"PostgreSQL 中未找到 tenant_id={tenant_id} 的运行配置")
        result = runtime.enqueue(
            RunRequest(
                flow_id=flow_id,
                tenant_id=tenant_id,
                batch_id=request.batch_id,
                trigger_mode="manual",
                source_url=request.source_url,
                topic_context=request.topic_context,
                additional_instruction=request.additional_instruction,
                image_additional_instruction=request.image_additional_instruction,
                tenant_runtime_config=TenantRuntimeConfig(payload=runtime_payload),
            )
        )
        return success_response(
            {
                "status": result["status"],
                "tenant_id": tenant_id,
                "flow_id": flow_id,
                "batch_id": result["batch_id"],
                "run_path": f"/api/flows/{flow_id}/runs/{result['batch_id']}",
                "current_node": result.get("current_node", ""),
                "current_node_index": result.get("current_node_index", 0),
                "total_node_count": result.get("total_node_count", 0),
                "completed_node_count": len(result.get("completed_nodes", [])),
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def resume_flow(
    flow_id: str,
    tenant_id: str,
    batch_id: str,
    runtime: Annotated[GraphRuntime, Depends(get_runtime)],
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    try:
        tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
        database_url = require_database(settings)
        runtime_payload = get_tenant_runtime_config(database_url, tenant_id)
        if runtime_payload is None:
            raise HTTPException(status_code=400, detail=f"PostgreSQL 中未找到 tenant_id={tenant_id} 的运行配置")
        state = load_run_state(settings, flow_id, tenant_id, batch_id)
        result = runtime.enqueue(
            RunRequest(
                flow_id=flow_id,
                tenant_id=tenant_id,
                batch_id=batch_id,
                trigger_mode=str(state.get("trigger_mode") or ""),
                source_url=str(state.get("source_url") or ""),
                topic_context=state.get("topic_context") if isinstance(state.get("topic_context"), dict) else {},
                additional_instruction=str(state.get("additional_instruction") or ""),
                image_additional_instruction=str(state.get("image_additional_instruction") or ""),
                tenant_runtime_config=TenantRuntimeConfig(payload=runtime_payload),
                resume=True,
            )
        )
        return success_response(
            {
                "status": result["status"],
                "tenant_id": tenant_id,
                "flow_id": flow_id,
                "batch_id": batch_id,
                "run_path": f"/api/flows/{flow_id}/runs/{batch_id}",
                "resume_count": result.get("resume_count", 0),
                "current_node": result.get("current_node", ""),
                "current_node_index": result.get("current_node_index", 0),
                "total_node_count": result.get("total_node_count", 0),
                "completed_node_count": len(result.get("completed_nodes", [])),
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def get_run(
    flow_id: str,
    tenant_id: str,
    batch_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(tenant_id, authenticated_tenant_id)
    return success_response(load_run_state(settings, flow_id, tenant_id, batch_id))


@router.get("/runs")
def list_runs(
    flow_id: str = "",
    status: str = "",
    limit: int = 20,
    offset: int = 0,
    settings: Annotated[WorkflowSettings, Depends(get_settings)] = None,
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)] = "",
) -> dict:
    tenant_id = _resolve_tenant_id(None, authenticated_tenant_id)
    database_url = require_database(settings)
    runs, total = list_workflow_runs(
        database_url,
        tenant_id=tenant_id,
        flow_id=flow_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    response = WorkflowRunListResponse(
        tenant_id=tenant_id,
        total=total,
        limit=max(1, min(int(limit), 200)),
        offset=max(0, int(offset)),
        runs=[_build_workflow_run_item(item) for item in runs],
    )
    return success_response(response.model_dump())


@router.get("/account/ledger")
def get_account_ledger(
    date_from: str = "",
    date_to: str = "",
    entry_type: Annotated[str, Query(pattern="^(|all|consume|recharge)$")] = "",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    settings: Annotated[WorkflowSettings, Depends(get_settings)] = None,
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)] = "",
) -> dict:
    tenant_id = _resolve_tenant_id(None, authenticated_tenant_id)
    database_url = require_database(settings)
    _ensure_wallet_seed_data(database_url, tenant_id)

    normalized_entry_type = ""
    if entry_type == "consume":
        normalized_entry_type = "consume"
    elif entry_type == "recharge":
        normalized_entry_type = "recharge"

    balance_summary = summarize_wallet_balance(database_url, tenant_id=tenant_id)
    period_summary = summarize_wallet_period(
        database_url,
        tenant_id=tenant_id,
        date_from=date_from or None,
        date_to=date_to or None,
    )
    breakdown = summarize_wallet_breakdown(
        database_url,
        tenant_id=tenant_id,
        date_from=date_from or None,
        date_to=date_to or None,
    )
    trend = summarize_wallet_daily_usage(
        database_url,
        tenant_id=tenant_id,
        date_from=date_from or None,
        date_to=date_to or None,
    )
    entries, total = list_wallet_ledger_entries(
        database_url,
        tenant_id=tenant_id,
        entry_type=normalized_entry_type,
        date_from=date_from or None,
        date_to=date_to or None,
        limit=limit,
        offset=offset,
    )

    response = WalletLedgerListResponse(
        tenant_id=tenant_id,
        total=total,
        limit=max(1, min(int(limit), 500)),
        offset=max(0, int(offset)),
        summary=WalletPeriodSummaryResponse(
            date_from=str(date_from or ""),
            date_to=str(date_to or ""),
            consume_total=period_summary["consume_total"],
            recharge_total=period_summary["recharge_total"],
        ),
        balance=WalletBalanceSummaryResponse(
            tenant_id=tenant_id,
            balance=balance_summary["balance"],
            recharge_total=balance_summary["recharge_total"],
            consume_total=balance_summary["consume_total"],
        ),
        breakdown=[
            WalletBreakdownItemResponse(
                channel=str(item["channel"]),
                amount=float(item["amount"]),
                entry_count=int(item["entry_count"]),
            )
            for item in breakdown
        ],
        trend=[
            WalletDailyUsageItemResponse(
                date=str(item["date"]),
                amount=float(item["amount"]),
            )
            for item in trend
        ],
        entries=[_build_wallet_entry_item(item) for item in entries],
    )
    return success_response(response.model_dump())


@router.get("/account/balance")
def get_account_balance(
    settings: Annotated[WorkflowSettings, Depends(get_settings)] = None,
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)] = "",
) -> dict:
    tenant_id = _resolve_tenant_id(None, authenticated_tenant_id)
    database_url = require_database(settings)
    _ensure_wallet_seed_data(database_url, tenant_id)
    balance_summary = summarize_wallet_balance(database_url, tenant_id=tenant_id)
    response = WalletBalanceSummaryResponse(
        tenant_id=tenant_id,
        balance=balance_summary["balance"],
        recharge_total=balance_summary["recharge_total"],
        consume_total=balance_summary["consume_total"],
    )
    return success_response(response.model_dump())


@router.get("/account/provider-monitors")
def get_account_provider_monitors(
    settings: Annotated[WorkflowSettings, Depends(get_settings)] = None,
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)] = "",
) -> dict:
    tenant_id = _resolve_tenant_id(None, authenticated_tenant_id)
    database_url = require_database(settings)
    cache_key = _provider_monitor_cache_key(database_url, tenant_id)
    cached_payload, is_fresh = _get_cached_provider_monitor_payload(cache_key)
    if cached_payload is not None and is_fresh:
        return success_response(cached_payload)

    _ensure_wallet_seed_data(database_url, tenant_id)
    runtime_payload = get_tenant_runtime_config(database_url, tenant_id) or {}

    try:
        payload = _build_provider_monitor_payload(
            settings=settings,
            tenant_id=tenant_id,
            runtime_payload=runtime_payload,
            database_url=database_url,
        )
        _store_provider_monitor_payload(cache_key, payload)
        return success_response(payload)
    except Exception:
        if cached_payload is not None and not _provider_monitor_payload_has_failure(cached_payload):
            return success_response(cached_payload)
        raise


@router.get("/artifacts")
def get_artifacts(
    flow_id: str = "",
    limit: int = 20,
    offset: int = 0,
    settings: Annotated[WorkflowSettings, Depends(get_settings)] = None,
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)] = "",
) -> dict:
    tenant_id = _resolve_tenant_id(None, authenticated_tenant_id)
    database_url = require_database(settings)
    items, total = list_artifacts(
        database_url,
        tenant_id=tenant_id,
        flow_id=flow_id,
        limit=limit,
        offset=offset,
    )
    response = ArtifactListResponse(
        tenant_id=tenant_id,
        total=total,
        limit=max(1, min(int(limit), 200)),
        offset=max(0, int(offset)),
        items=[_build_artifact_item(item) for item in items],
    )
    return success_response(response.model_dump())


@router.get("/artifacts/{artifact_id}")
def get_artifact_detail(
    artifact_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(None, authenticated_tenant_id)
    database_url = require_database(settings)
    artifact = get_artifact(database_url, tenant_id=tenant_id, artifact_id=artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    return success_response(_build_artifact_item(artifact).model_dump())


@router.put("/artifacts/{artifact_id}")
def update_artifact_detail(
    artifact_id: str,
    request: ArtifactUpdateRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(None, authenticated_tenant_id)
    database_url = require_database(settings)
    artifact = update_artifact(
        database_url,
        tenant_id=tenant_id,
        artifact_id=artifact_id,
        title=request.title,
        content=request.content,
        tags=request.tags,
        cover_prompt=request.cover_prompt,
        cover_url=request.cover_url,
        image_prompts=request.image_prompts,
        image_urls=request.image_urls,
        payload=request.payload,
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    return success_response(_build_artifact_item(artifact).model_dump())


@router.delete("/artifacts/{artifact_id}")
def delete_artifact_detail(
    artifact_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(None, authenticated_tenant_id)
    database_url = require_database(settings)
    deleted = delete_artifact(database_url, tenant_id=tenant_id, artifact_id=artifact_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="artifact not found")
    return success_response(
        {
            "tenant_id": tenant_id,
            "artifact_id": artifact_id,
            "deleted": True,
        }
    )


@router.post("/artifacts/{artifact_id}/regenerate-image")
def regenerate_artifact_image(
    artifact_id: str,
    request: ArtifactRegenerateImageRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(None, authenticated_tenant_id)
    database_url = require_database(settings)
    artifact = get_artifact(database_url, tenant_id=tenant_id, artifact_id=artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="artifact not found")

    runtime_payload = get_tenant_runtime_config(database_url, tenant_id)
    if runtime_payload is None:
        raise HTTPException(status_code=400, detail=f"PostgreSQL 涓湭鎵惧埌 tenant_id={tenant_id} 鐨勮繍琛岄厤缃?")

    image_index = int(request.image_index)
    current_image_prompts = list(artifact.image_prompts)
    current_image_urls = list(artifact.image_urls)
    preview = _generate_artifact_image_edit_preview(
        artifact,
        image_index=image_index,
        prompt=request.prompt,
        settings=settings,
        tenant_config=runtime_payload,
        billing_context={
            "tenant_id": tenant_id,
            "title": "作品图片重绘",
            "channel": "图片生成",
            "feature_key": "artifact-regenerate-image",
            "detail": "已记录作品图片重绘调用",
            "request_id": f"artifact:{artifact_id}:regenerate:{image_index}",
            "related_resource_type": "artifact",
            "related_resource_id": artifact_id,
            "artifact_id": artifact_id,
            "image_index": image_index,
        },
    )
    next_prompt = preview["prompt"]
    generated_url = preview["generated_url"]

    next_cover_prompt = artifact.cover_prompt
    next_cover_url = artifact.cover_url
    next_image_prompts = current_image_prompts
    next_image_urls = current_image_urls

    if image_index == 0:
        next_cover_prompt = next_prompt
        next_cover_url = generated_url
    else:
        image_prompt_index = image_index - 1
        next_image_prompts[image_prompt_index] = next_prompt
        next_image_urls[image_prompt_index] = generated_url

    merged_payload = _merge_artifact_payload(
        artifact,
        title=artifact.title,
        content=artifact.content,
        tags=artifact.tags,
        cover_prompt=next_cover_prompt,
        image_prompts=_normalize_string_list(next_image_prompts),
        cover_url=next_cover_url,
        image_urls=_normalize_string_list(next_image_urls),
    )
    merged_payload["last_regenerated_image_index"] = image_index

    updated = update_artifact(
        database_url,
        tenant_id=tenant_id,
        artifact_id=artifact_id,
        cover_prompt=next_cover_prompt,
        cover_url=next_cover_url,
        image_prompts=next_image_prompts,
        image_urls=next_image_urls,
        payload=merged_payload,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    return success_response(_build_artifact_item(updated).model_dump())


@router.post("/artifacts/{artifact_id}/preview-image-edit")
def preview_artifact_image_edit(
    artifact_id: str,
    request: ArtifactPreviewImageEditRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    tenant_id = _resolve_tenant_id(None, authenticated_tenant_id)
    database_url = require_database(settings)
    artifact = get_artifact(database_url, tenant_id=tenant_id, artifact_id=artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="artifact not found")

    runtime_payload = get_tenant_runtime_config(database_url, tenant_id)
    if runtime_payload is None:
        raise HTTPException(status_code=400, detail=f"PostgreSQL 涓湭鎵惧埌 tenant_id={tenant_id} 鐨勮繍琛岄厤缃?")

    preview = _generate_artifact_image_edit_preview(
        artifact,
        image_index=int(request.image_index),
        prompt=request.prompt,
        settings=settings,
        tenant_config=runtime_payload,
        billing_context={
            "tenant_id": tenant_id,
            "title": "作品图片预览重绘",
            "channel": "图片生成",
            "feature_key": "artifact-preview-image-edit",
            "detail": "已记录作品图片预览重绘调用",
            "request_id": f"artifact:{artifact_id}:preview:{int(request.image_index)}",
            "related_resource_type": "artifact",
            "related_resource_id": artifact_id,
            "artifact_id": artifact_id,
            "image_index": int(request.image_index),
        },
    )
    return success_response(
        {
            "generated_url": preview["generated_url"],
            "image_index": preview["image_index"],
            "prompt": preview["prompt"],
        }
    )


@router.get("/schedules")
def get_schedules(
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return get_tenant_schedules(authenticated_tenant_id, settings, authenticated_tenant_id)


@router.get("/tables")
def list_tables(
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return list_tenant_tables(authenticated_tenant_id, settings, authenticated_tenant_id)


@router.get("/tables/{dataset_key}")
def get_table_rows(
    dataset_key: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    summary: bool = False,
) -> dict:
    return get_tenant_table_rows(
        authenticated_tenant_id,
        dataset_key,
        settings,
        authenticated_tenant_id,
        limit=limit,
        offset=offset,
        order=order,
        summary=summary,
    )


@router.get("/tables/{dataset_key}/{record_id}")
def get_table_row(
    dataset_key: str,
    record_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return get_tenant_table_row(authenticated_tenant_id, dataset_key, record_id, settings, authenticated_tenant_id)


@router.post("/tables/{dataset_key}")
def create_table_row(
    dataset_key: str,
    request: DatasetTableRowRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return create_tenant_table_row(authenticated_tenant_id, dataset_key, request, settings, authenticated_tenant_id)


@router.put("/tables/{dataset_key}/{record_id}")
def update_table_row(
    dataset_key: str,
    record_id: str,
    request: DatasetTableRowRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return update_tenant_table_row(authenticated_tenant_id, dataset_key, record_id, request, settings, authenticated_tenant_id)


@router.delete("/tables/{dataset_key}/{record_id}")
def delete_table_row(
    dataset_key: str,
    record_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return delete_tenant_table_row(authenticated_tenant_id, dataset_key, record_id, settings, authenticated_tenant_id)


@router.get("/schedules/{flow_id}")
def get_schedule(
    flow_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return get_tenant_schedule(authenticated_tenant_id, flow_id, settings, authenticated_tenant_id)


@router.put("/schedules/{flow_id}")
def put_schedule(
    flow_id: str,
    request: UpsertTenantFlowScheduleRequest,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return put_tenant_schedule(authenticated_tenant_id, flow_id, request, settings, authenticated_tenant_id)


@router.delete("/schedules/{flow_id}")
def delete_schedule(
    flow_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return delete_tenant_schedule(authenticated_tenant_id, flow_id, settings, authenticated_tenant_id)


@router.post("/schedules/{flow_id}/trigger")
def trigger_schedule(
    flow_id: str,
    runtime: Annotated[GraphRuntime, Depends(get_runtime)],
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return trigger_tenant_schedule(authenticated_tenant_id, flow_id, runtime, settings, authenticated_tenant_id)


@router.post("/flows/{flow_id}/runs/{batch_id}/resume")
def resume_authenticated_flow(
    flow_id: str,
    batch_id: str,
    runtime: Annotated[GraphRuntime, Depends(get_runtime)],
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return resume_flow(flow_id, authenticated_tenant_id, batch_id, runtime, settings, authenticated_tenant_id)


@router.get("/flows/{flow_id}/runs/{batch_id}")
def get_authenticated_run(
    flow_id: str,
    batch_id: str,
    settings: Annotated[WorkflowSettings, Depends(get_settings)],
    authenticated_tenant_id: Annotated[str, Depends(require_tenant_api_key)],
) -> dict:
    return get_run(flow_id, authenticated_tenant_id, batch_id, settings, authenticated_tenant_id)
