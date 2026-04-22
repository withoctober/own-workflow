from __future__ import annotations

from typing import Any

from typing_extensions import Annotated, TypedDict


def merge_dict(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    merged.update(right)
    return merged


def merge_list(left: list[Any], right: list[Any]) -> list[Any]:
    return [*left, *right]


class WorkflowState(TypedDict, total=False):
    outputs: Annotated[dict[str, Any], merge_dict]
    artifacts: Annotated[dict[str, list[str]], merge_dict]
    messages: Annotated[list[str], merge_list]
    errors: Annotated[list[str], merge_list]
    status: str
