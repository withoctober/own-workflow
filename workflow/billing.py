from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urlsplit

from model import create_provider_usage_event, create_wallet_ledger_entry, ensure_postgres_tables, postgres_enabled
BILLING_LLM_INPUT_COST_PER_1K_TOKENS_ENV = "BILLING_LLM_INPUT_COST_PER_1K_TOKENS"
BILLING_LLM_OUTPUT_COST_PER_1K_TOKENS_ENV = "BILLING_LLM_OUTPUT_COST_PER_1K_TOKENS"
BILLING_TIKHUB_REQUEST_COST_ENV = "BILLING_TIKHUB_REQUEST_COST"
BILLING_IMAGE_GENERATION_COST_PER_IMAGE_ENV = "BILLING_IMAGE_GENERATION_COST_PER_IMAGE"
BILLING_IMAGE_EDIT_COST_PER_IMAGE_ENV = "BILLING_IMAGE_EDIT_COST_PER_IMAGE"
DEFAULT_BILLING_CURRENCY = "CNY"

_ENSURED_DATABASE_URLS: set[str] = set()
_ENSURE_DATABASE_LOCK = Lock()


def _as_path(root: Path | str | None) -> Path | None:
    if root is None:
        return None
    if isinstance(root, Path):
        return root
    text = str(root).strip()
    return Path(text).resolve() if text else None


def _env_value(name: str, root: Path) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    env_file = root / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if not line or line.strip().startswith("#") or "=" not in line:
            continue
        key, raw = line.split("=", 1)
        if key.strip() == name:
            return raw.strip().strip("'\"")
    return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _read_float_env(root: Path | str | None, name: str) -> float:
    path = _as_path(root)
    if path is None:
        return 0.0
    return max(0.0, _to_float(_env_value(name, path)) or 0.0)


def _resolve_database_url(
    *,
    root: Path | str | None = None,
    database_url: str = "",
    tenant_config: Any = None,
) -> str:
    normalized = str(database_url).strip()
    if normalized:
        return normalized
    tenant_database_url = str(getattr(tenant_config, "database_url", "") or "").strip()
    if tenant_database_url:
        return tenant_database_url
    path = _as_path(root)
    if path is None:
        return ""
    return str(_env_value("DATABASE_URL", path) or "").strip()


def _ensure_database(database_url: str) -> None:
    if not postgres_enabled(database_url):
        return
    if database_url not in _ENSURED_DATABASE_URLS:
        with _ENSURE_DATABASE_LOCK:
            if database_url not in _ENSURED_DATABASE_URLS:
                ensure_postgres_tables(database_url)
                _ENSURED_DATABASE_URLS.add(database_url)


def _clean_dict(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return {str(key): value for key, value in payload.items()}


def _default_provider(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    return normalized or "system"


def resolve_llm_provider(base_url: str) -> str:
    hostname = urlsplit(str(base_url).strip()).hostname or ""
    normalized = hostname.lower()
    if "openai" in normalized or "right.codes" in normalized:
        return "openai"
    return "llm"


def extract_llm_usage(response: Any) -> dict[str, Any]:
    usage_metadata = getattr(response, "usage_metadata", None)
    response_metadata = getattr(response, "response_metadata", None)
    usage = usage_metadata if isinstance(usage_metadata, dict) else {}
    response_meta = response_metadata if isinstance(response_metadata, dict) else {}
    token_usage = response_meta.get("token_usage") if isinstance(response_meta.get("token_usage"), dict) else {}

    tokens_in = _to_int(
        usage.get("input_tokens")
        or usage.get("prompt_tokens")
        or token_usage.get("prompt_tokens")
        or token_usage.get("input_tokens")
    )
    tokens_out = _to_int(
        usage.get("output_tokens")
        or usage.get("completion_tokens")
        or token_usage.get("completion_tokens")
        or token_usage.get("output_tokens")
    )
    total_tokens = _to_int(
        usage.get("total_tokens")
        or token_usage.get("total_tokens")
        or (tokens_in + tokens_out)
    )
    return {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "total_tokens": total_tokens,
        "model_name": str(response_meta.get("model_name") or "").strip(),
        "response_id": str(response_meta.get("id") or response_meta.get("request_id") or "").strip(),
        "response_metadata": response_meta,
    }


def calculate_llm_amount(
    root: Path | str | None,
    *,
    tokens_in: int,
    tokens_out: int,
) -> float:
    input_rate = _read_float_env(root, BILLING_LLM_INPUT_COST_PER_1K_TOKENS_ENV)
    output_rate = _read_float_env(root, BILLING_LLM_OUTPUT_COST_PER_1K_TOKENS_ENV)
    amount = (max(0, tokens_in) / 1000.0) * input_rate + (max(0, tokens_out) / 1000.0) * output_rate
    return round(max(0.0, amount), 4)


def _build_event_id(
    *,
    provider: str,
    tenant_id: str,
    channel: str,
    feature_key: str,
    model_name: str,
    related_resource_type: str,
    related_resource_id: str,
    request_id: str,
    payload: dict[str, Any],
) -> str:
    fingerprint = json.dumps(
        {
            "provider": provider,
            "tenant_id": tenant_id,
            "channel": channel,
            "feature_key": feature_key,
            "model_name": model_name,
            "related_resource_type": related_resource_type,
            "related_resource_id": related_resource_id,
            "request_id": request_id,
            "payload": payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:24]
    return f"{provider}-{digest}"


def _extract_amount_from_payload(payload: dict[str, Any]) -> float | None:
    candidates = [
        payload.get("amount"),
        payload.get("cost"),
        payload.get("price"),
        payload.get("billing_amount"),
    ]
    for value in candidates:
        normalized = _to_float(value)
        if normalized is not None:
            return max(0.0, normalized)
    return None


def record_usage_event(
    *,
    root: Path | str | None = None,
    database_url: str = "",
    tenant_config: Any = None,
    tenant_id: str,
    provider: str,
    channel: str,
    title: str,
    detail: str = "",
    feature_key: str = "",
    model_name: str = "",
    request_id: str = "",
    provider_event_id: str = "",
    related_resource_type: str = "",
    related_resource_id: str = "",
    amount: float | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    image_count: int = 0,
    request_count: int = 0,
    payload: dict[str, Any] | None = None,
    currency: str = DEFAULT_BILLING_CURRENCY,
    occurred_at: Any = None,
) -> dict[str, Any] | None:
    normalized_tenant_id = str(tenant_id or "").strip()
    normalized_provider = _default_provider(provider)
    normalized_channel = str(channel or "").strip()
    normalized_title = str(title or "").strip()
    if not normalized_tenant_id or not normalized_provider or not normalized_channel or not normalized_title:
        return None

    resolved_database_url = _resolve_database_url(root=root, database_url=database_url, tenant_config=tenant_config)
    if not resolved_database_url:
        return None

    _ensure_database(resolved_database_url)
    normalized_payload = _clean_dict(payload)
    normalized_payload.setdefault("currency", str(currency or DEFAULT_BILLING_CURRENCY).strip() or DEFAULT_BILLING_CURRENCY)
    normalized_payload.setdefault("request_count", max(0, int(request_count)))
    if tokens_in > 0:
        normalized_payload["tokens_in"] = max(0, int(tokens_in))
    if tokens_out > 0:
        normalized_payload["tokens_out"] = max(0, int(tokens_out))
    if image_count > 0:
        normalized_payload["image_count"] = max(0, int(image_count))
    if request_id:
        normalized_payload["request_id"] = str(request_id).strip()

    resolved_amount = _to_float(amount)
    if resolved_amount is None:
        resolved_amount = _extract_amount_from_payload(normalized_payload)
    if resolved_amount is None and (tokens_in > 0 or tokens_out > 0):
        resolved_amount = calculate_llm_amount(root, tokens_in=tokens_in, tokens_out=tokens_out)
        normalized_payload.setdefault("price_source", "llm_token_rates")
    if resolved_amount is None and normalized_provider == "tikhub":
        resolved_amount = max(0, int(request_count) or 1) * _read_float_env(root, BILLING_TIKHUB_REQUEST_COST_ENV)
        normalized_payload.setdefault("price_source", "tikhub_request_rate")
    if resolved_amount is None and image_count > 0:
        env_name = BILLING_IMAGE_EDIT_COST_PER_IMAGE_ENV if "重绘" in normalized_title or "编辑" in normalized_title else BILLING_IMAGE_GENERATION_COST_PER_IMAGE_ENV
        resolved_amount = max(0, int(image_count)) * _read_float_env(root, env_name)
        normalized_payload.setdefault("price_source", "image_count_rate")

    final_amount = round(max(0.0, resolved_amount or 0.0), 4)
    status = "completed" if final_amount > 0 else "recorded"
    final_provider_event_id = str(provider_event_id or "").strip() or _build_event_id(
        provider=normalized_provider,
        tenant_id=normalized_tenant_id,
        channel=normalized_channel,
        feature_key=str(feature_key or "").strip(),
        model_name=str(model_name or "").strip(),
        related_resource_type=str(related_resource_type or "").strip(),
        related_resource_id=str(related_resource_id or "").strip(),
        request_id=str(request_id or "").strip(),
        payload=normalized_payload,
    )

    ledger_entry = create_wallet_ledger_entry(
        resolved_database_url,
        tenant_id=normalized_tenant_id,
        entry_type="consume",
        amount=-final_amount if final_amount > 0 else 0.0,
        title=normalized_title,
        channel=normalized_channel,
        provider=normalized_provider,
        provider_event_id=final_provider_event_id,
        related_resource_type=str(related_resource_type or "").strip(),
        related_resource_id=str(related_resource_id or "").strip(),
        status=status,
        detail=str(detail or "").strip(),
        metadata=normalized_payload,
        occurred_at=occurred_at,
    )
    provider_usage = create_provider_usage_event(
        resolved_database_url,
        tenant_id=normalized_tenant_id,
        provider=normalized_provider,
        provider_event_id=final_provider_event_id,
        request_id=str(request_id or "").strip(),
        channel=normalized_channel,
        feature_key=str(feature_key or "").strip(),
        model_name=str(model_name or "").strip(),
        tokens_in=max(0, int(tokens_in)),
        tokens_out=max(0, int(tokens_out)),
        image_count=max(0, int(image_count)),
        amount=final_amount,
        currency=str(currency or DEFAULT_BILLING_CURRENCY).strip() or DEFAULT_BILLING_CURRENCY,
        related_resource_type=str(related_resource_type or "").strip(),
        related_resource_id=str(related_resource_id or "").strip(),
        ledger_entry_id=ledger_entry.id,
        status=status,
        payload=normalized_payload,
        occurred_at=occurred_at,
    )
    return {
        "provider_event_id": final_provider_event_id,
        "amount": final_amount,
        "status": status,
        "ledger_entry_id": ledger_entry.id,
        "provider_usage_event_id": provider_usage.id,
    }


def record_llm_usage(
    root: Path | str | None,
    *,
    response: Any,
    tenant_id: str,
    base_url: str,
    title: str,
    channel: str,
    feature_key: str = "",
    related_resource_type: str = "",
    related_resource_id: str = "",
    request_id: str = "",
    provider_event_id: str = "",
    payload: dict[str, Any] | None = None,
    tenant_config: Any = None,
) -> dict[str, Any] | None:
    usage = extract_llm_usage(response)
    provider = resolve_llm_provider(base_url)
    normalized_payload = _clean_dict(payload)
    normalized_payload["provider_base_url"] = str(base_url or "").strip()
    response_meta = usage.get("response_metadata")
    if isinstance(response_meta, dict):
        normalized_payload["response_metadata"] = response_meta
    return record_usage_event(
        root=root,
        tenant_config=tenant_config,
        tenant_id=tenant_id,
        provider=provider,
        channel=channel,
        title=title,
        detail=f"{normalized_title_or_default(title)} 已记录模型调用",
        feature_key=feature_key,
        model_name=str(usage.get("model_name") or "").strip(),
        request_id=str(request_id or usage.get("response_id") or "").strip(),
        provider_event_id=provider_event_id,
        related_resource_type=related_resource_type,
        related_resource_id=related_resource_id,
        tokens_in=_to_int(usage.get("tokens_in")),
        tokens_out=_to_int(usage.get("tokens_out")),
        payload=normalized_payload,
    )


def normalized_title_or_default(value: str) -> str:
    normalized = str(value or "").strip()
    return normalized or "模型调用"


__all__ = [
    "BILLING_IMAGE_EDIT_COST_PER_IMAGE_ENV",
    "BILLING_IMAGE_GENERATION_COST_PER_IMAGE_ENV",
    "BILLING_LLM_INPUT_COST_PER_1K_TOKENS_ENV",
    "BILLING_LLM_OUTPUT_COST_PER_1K_TOKENS_ENV",
    "BILLING_TIKHUB_REQUEST_COST_ENV",
    "DEFAULT_BILLING_CURRENCY",
    "calculate_llm_amount",
    "extract_llm_usage",
    "record_llm_usage",
    "record_usage_event",
    "resolve_llm_provider",
]
