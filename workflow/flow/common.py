from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from workflow.runtime.context import RuntimeContext


def persist_step_output(
    runtime: RuntimeContext,
    state: dict[str, Any],
    *,
    step_id: str,
    output: Any = None,
    artifacts: list[str] | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if output is not None:
        patch["outputs"] = {step_id: output}

    patch["artifacts"] = {step_id: artifacts or []}

    if message:
        patch["messages"] = [message]
    return patch


def write_artifact(runtime: RuntimeContext, step_id: str, filename: str, payload: Any) -> str:
    path = runtime.artifacts_dir / step_id / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, (dict, list)):
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        path.write_text(str(payload), encoding="utf-8")
    return str(path)


def block_state(runtime: RuntimeContext, state: dict[str, Any], message: str) -> dict[str, Any]:
    return {"status": "blocked", "errors": [message]}


def soft_fail_state(
    runtime: RuntimeContext,
    state: dict[str, Any],
    *,
    step_id: str,
    message: str,
    output: Any = None,
    artifacts: list[str] | None = None,
) -> dict[str, Any]:
    patch: dict[str, Any] = {
        "status": "soft_failed",
        "messages": [message],
        "artifacts": {step_id: artifacts or []},
    }
    if output is not None:
        patch["outputs"] = {step_id: output}
    return patch


def skip_if_blocked(state: dict[str, Any]) -> dict[str, Any] | None:
    if str(state.get("status", "")).strip().lower() == "blocked":
        return {}
    if state.get("errors"):
        return {}
    return None
