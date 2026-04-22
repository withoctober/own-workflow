from __future__ import annotations

import json
import urllib.request
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from workflow.core.env import env_value


API_USER_AGENT = "OpenClaw-HotspotFetcher/1.0"
SOURCE_NAME = "小红书-搜索发现热榜"
TZ_NAME = "Asia/Shanghai"
DEFAULT_ENDPOINT = "https://api.tikhub.io/api/v1/xiaohongshu/web_v2/fetch_hot_list"


def today_str() -> str:
    return datetime.now(ZoneInfo(TZ_NAME)).strftime("%Y-%m-%d")


def fetch_raw(api_key: str, endpoint: str, *, timeout: int = 30) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": API_USER_AGENT,
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("hotspots_response_not_object")
    return payload


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    outer_code = raw.get("code")
    outer_message = raw.get("message")
    outer_data = raw.get("data") or {}
    if not isinstance(outer_data, dict):
        outer_data = {}
    inner_code = outer_data.get("code")
    inner_message = outer_data.get("message")
    biz = outer_data.get("data") or {}
    if not isinstance(biz, dict):
        biz = {}
    items = biz.get("items") or []
    if not isinstance(items, list):
        items = []

    normalized_items: list[dict[str, Any]] = []
    today = today_str()
    for item in items:
        if not isinstance(item, dict):
            continue
        fields: dict[str, Any] = {
            "日期": today,
            "热榜标题": item.get("title", ""),
            "热点来源": SOURCE_NAME,
            "热度值": item.get("score", ""),
            "榜单标签": item.get("word_type", ""),
            "榜单类型": item.get("type", ""),
            "排名变化": str(item.get("rank_change", "")),
            "热点ID": item.get("id", ""),
            "榜单ID": biz.get("hot_list_id", ""),
        }
        icon = item.get("icon")
        if isinstance(icon, str) and icon.strip():
            fields["图标链接"] = {"link": icon.strip(), "text": "icon"}
        title_img = item.get("title_img")
        if isinstance(title_img, str) and title_img.strip():
            fields["标题图片链接"] = {"link": title_img.strip(), "text": "title-img"}
        normalized_items.append({"raw": item, "fields": fields})

    return {
        "ok": outer_code == 200 and inner_code == 0 and bool(normalized_items),
        "date": today,
        "source": SOURCE_NAME,
        "api": {
            "outer_code": outer_code,
            "outer_message": outer_message,
            "inner_code": inner_code,
            "inner_message": inner_message,
        },
        "board": {
            "title": biz.get("title", ""),
            "hot_list_id": biz.get("hot_list_id", ""),
            "count": len(normalized_items),
        },
        "items": normalized_items,
    }


def extract_hotspot_rows(normalized: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item.get("fields", {})
        for item in normalized.get("items", [])
        if isinstance(item, dict) and isinstance(item.get("fields"), dict)
    ]


def dedupe_today_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        date_value = str(row.get("日期", "")).strip()
        hotspot_id = str(row.get("热点ID", "")).strip()
        dedupe_key = (date_value, hotspot_id)
        if hotspot_id and dedupe_key in seen:
            continue
        if hotspot_id:
            seen.add(dedupe_key)
        deduped.append(row)
    return deduped


def keep_rows_except_today(rows: list[dict[str, Any]], today_value: str) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("日期", "")).strip() == today_value:
            continue
        kept.append(row)
    return kept


def merge_hotspot_rows(existing_rows: list[dict[str, Any]], normalized: dict[str, Any]) -> dict[str, Any]:
    today_value = str(normalized.get("date", "")).strip()
    today_rows = dedupe_today_rows(extract_hotspot_rows(normalized))
    merged_rows = keep_rows_except_today(existing_rows, today_value) + today_rows
    board = normalized.get("board", {}) if isinstance(normalized.get("board"), dict) else {}
    return {
        "date": today_value,
        "rows": today_rows,
        "merged_rows": merged_rows,
        "summary": {
            "date": today_value,
            "board_title": str(board.get("title", "")).strip(),
            "board_id": str(board.get("hot_list_id", "")).strip(),
            "row_count": len(today_rows),
            "merged_row_count": len(merged_rows),
            "source": str(normalized.get("source", "")).strip(),
        },
    }


def fetch_and_normalize(root, *, api_key_env: str = "TIKHUB_API_KEY", endpoint: str = DEFAULT_ENDPOINT) -> dict[str, Any]:
    normalized_api_env = str(api_key_env).strip() or "TIKHUB_API_KEY"
    normalized_endpoint = str(endpoint).strip() or DEFAULT_ENDPOINT
    api_key = env_value(normalized_api_env, root)
    if not api_key:
        raise RuntimeError(f"missing_api_key:{normalized_api_env}")
    if not normalized_endpoint:
        raise RuntimeError("missing_endpoint")
    return normalize(fetch_raw(api_key, normalized_endpoint))


def fetch_daily_hotspots(
    root,
    *,
    api_key_env: str = "TIKHUB_API_KEY",
    endpoint: str = DEFAULT_ENDPOINT,
) -> dict[str, Any]:
    return fetch_and_normalize(root, api_key_env=api_key_env, endpoint=endpoint)


def fetch_daily_hotspots_from_step(root, step: dict[str, Any] | None = None) -> dict[str, Any]:
    step_payload = step if isinstance(step, dict) else {}
    api_config = step_payload.get("api_config", {}) if isinstance(step_payload.get("api_config"), dict) else {}
    api_key_env = str(api_config.get("api_key_env", "TIKHUB_API_KEY")).strip() or "TIKHUB_API_KEY"
    endpoint = str(api_config.get("hot_list_endpoint", DEFAULT_ENDPOINT)).strip() or DEFAULT_ENDPOINT
    return fetch_and_normalize(root, api_key_env=api_key_env, endpoint=endpoint)
