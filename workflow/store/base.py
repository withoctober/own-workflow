from __future__ import annotations

import json
from typing import Any, Protocol


class Store(Protocol):
    def read_table(self, name: str) -> list[dict[str, Any]]:
        ...

    def list_table_fields(self, name: str) -> list[str]:
        ...

    def write_table(self, name: str, records: list[dict[str, Any]], mode: str = "replace") -> str:
        ...

    def update_table_records(self, name: str, records: list[dict[str, Any]]) -> str:
        ...

    def delete_table(self, name: str) -> str:
        ...

    def read_doc(self, name: str) -> str:
        ...

    def write_doc(self, name: str, content: str, mode: str = "replace") -> str:
        ...

    def delete_doc(self, name: str) -> str:
        ...

    def target_exists(self, name: str) -> bool:
        ...


class StoreError(RuntimeError):
    """Store layer shared error."""


def normalize_table_mode(mode: str) -> str:
    value = mode.strip().lower()
    if value.startswith("append"):
        return "append"
    return "replace"


def normalize_doc_mode(mode: str) -> str:
    value = mode.strip().lower()
    if value.startswith("append"):
        return "append"
    return "replace"


def parse_json_safely(raw: str) -> dict[str, Any] | list[Any] | str:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def chunked(items: list[Any], size: int) -> list[list[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def backoff_seconds(attempt: int) -> float:
    return min(4.0, 0.5 * (2**attempt))


def merge_nested_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_nested_dicts(as_dict(merged.get(key)), as_dict(value))
            continue
        merged[key] = value
    return merged


def non_empty_count(record: dict[str, Any], fields: list[str]) -> int:
    count = 0
    for field in fields:
        value = record.get(field)
        if value is not None and str(value).strip():
            count += 1
    return count


def first_text(records: list[dict[str, Any]], *fields: str, default: str = "") -> str:
    for record in records:
        for field in fields:
            value = record.get(field)
            if value is not None and str(value).strip():
                return str(value).strip()
    return default
