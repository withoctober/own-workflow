from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
from dataclasses import dataclass
from urllib import error, parse, request


HOST = "billing.volcengineapi.com"
REGION = "cn-north-1"
SERVICE = "billing"
ACTION = "QueryBalanceAcct"
VERSION = "2022-01-01"
CONTENT_TYPE = "application/json; charset=utf-8"


@dataclass
class BalanceResult:
    available_balance: float | None


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _build_signing_key(secret_key: str, date_stamp: str) -> bytes:
    secret = f"VOLC{secret_key}".encode("utf-8")
    k_date = _sign(secret, date_stamp)
    k_region = hmac.new(k_date, REGION.encode("utf-8"), hashlib.sha256).digest()
    k_service = hmac.new(k_region, SERVICE.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(k_service, b"request", hashlib.sha256).digest()


def _normalize_balance(raw: object) -> float | None:
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        value = raw.strip()
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            return None
    return None


def query_balance_acct(*, access_key: str, secret_key: str, timeout: float = 3.0) -> BalanceResult | None:
    normalized_ak = str(access_key or "").strip()
    normalized_sk = str(secret_key or "").strip()
    if not normalized_ak or not normalized_sk:
        return None

    now = dt.datetime.now(dt.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    query = "&".join(
        [
            f"Action={parse.quote(ACTION, safe='-_.~')}",
            f"Version={parse.quote(VERSION, safe='-_.~')}",
        ]
    )
    payload = "{}"
    payload_hash = _sha256_hex(payload)
    canonical_headers = (
        f"content-type:{CONTENT_TYPE}\n"
        f"host:{HOST}\n"
        f"x-date:{amz_date}\n"
    )
    signed_headers = "content-type;host;x-date"
    canonical_request = "\n".join(
        [
            "POST",
            "/",
            query,
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )
    credential_scope = f"{date_stamp}/{REGION}/{SERVICE}/request"
    string_to_sign = "\n".join(
        [
            "HMAC-SHA256",
            amz_date,
            credential_scope,
            _sha256_hex(canonical_request),
        ]
    )
    signing_key = _build_signing_key(normalized_sk, date_stamp)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        "HMAC-SHA256 "
        f"Credential={normalized_ak}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )

    req = request.Request(
        f"https://{HOST}/?{query}",
        data=payload.encode("utf-8"),
        headers={
            "Content-Type": CONTENT_TYPE,
            "Host": HOST,
            "X-Date": amz_date,
            "Authorization": authorization,
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except (error.HTTPError, error.URLError, TimeoutError, ValueError):
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None

    result = parsed.get("Result") if isinstance(parsed, dict) else None
    if not isinstance(result, dict):
        return None

    return BalanceResult(available_balance=_normalize_balance(result.get("AvailableBalance")))
