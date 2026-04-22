from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from workflow.runtime.context import RuntimeContext


def summarize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {"type": "dict", "keys": sorted(str(key) for key in value.keys())[:20], "size": len(value)}
    if isinstance(value, list):
        return {"type": "list", "size": len(value)}
    if isinstance(value, str):
        text = value.strip()
        return {"type": "str", "length": len(text), "preview": text[:120]}
    if value is None:
        return {"type": "none"}
    return {"type": type(value).__name__, "value": str(value)[:120]}


def log_node_step(
    runtime: RuntimeContext,
    *,
    step_id: str,
    event: str,
    message: str,
    detail: dict[str, Any] | None = None,
    level: str = "info",
    duration_ms: int | None = None,
) -> None:
    runtime.log_node_event(
        step_id=step_id,
        event=event,
        message=message,
        detail=detail,
        level=level,
        duration_ms=duration_ms,
    )


def log_timed_step(
    runtime: RuntimeContext,
    *,
    step_id: str,
    phase: str,
    message: str,
    detail: dict[str, Any] | None = None,
) -> float:
    log_node_step(
        runtime,
        step_id=step_id,
        event=f"{phase}_started",
        message=message,
        detail=detail,
    )
    return time.perf_counter()


def finish_timed_step(
    runtime: RuntimeContext,
    *,
    step_id: str,
    phase: str,
    started_at: float,
    message: str,
    detail: dict[str, Any] | None = None,
    level: str = "info",
) -> None:
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    log_node_step(
        runtime,
        step_id=step_id,
        event=f"{phase}_finished",
        message=message,
        detail=detail,
        level=level,
        duration_ms=duration_ms,
    )


def fail_timed_step(
    runtime: RuntimeContext,
    *,
    step_id: str,
    phase: str,
    started_at: float,
    message: str,
    detail: dict[str, Any] | None = None,
    level: str = "error",
) -> None:
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    log_node_step(
        runtime,
        step_id=step_id,
        event=f"{phase}_failed",
        message=message,
        detail=detail,
        level=level,
        duration_ms=duration_ms,
    )


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
    log_node_step(
        runtime,
        step_id=step_id,
        event="step_output",
        message=message or "节点已产生输出",
        detail={
            "output": summarize_value(output),
            "artifact_count": len(artifacts or []),
        },
    )
    return patch


def write_artifact(runtime: RuntimeContext, step_id: str, filename: str, payload: Any) -> str:
    path = runtime.artifacts_dir / step_id / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, (dict, list)):
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        path.write_text(str(payload), encoding="utf-8")
    log_node_step(
        runtime,
        step_id=step_id,
        event="artifact_written",
        message=f"已写入工件 {filename}",
        detail={
            "path": str(path),
            "payload": summarize_value(payload),
        },
    )
    return str(path)


def write_named_artifacts(
    runtime: RuntimeContext,
    step_id: str,
    artifacts: dict[str, Any] | None = None,
) -> list[str]:
    written: list[str] = []
    for filename, payload in (artifacts or {}).items():
        written.append(write_artifact(runtime, step_id, filename, payload))
    return written


def write_stage_snapshot(
    runtime: RuntimeContext,
    *,
    step_id: str,
    phase: str,
    detail: dict[str, Any] | None = None,
    payload: Any = None,
) -> list[str]:
    artifacts: dict[str, Any] = {}
    if detail is not None:
        artifacts[f"{phase}.detail.json"] = detail
    if payload is not None:
        artifacts[f"{phase}.payload.json"] = payload
    return write_named_artifacts(runtime, step_id, artifacts)


def write_failure_snapshot(
    runtime: RuntimeContext,
    *,
    step_id: str,
    phase: str,
    error: str,
    detail: dict[str, Any] | None = None,
    payload: Any = None,
) -> list[str]:
    snapshot = {
        "phase": phase,
        "error": error,
        "detail": detail or {},
    }
    artifacts: dict[str, Any] = {
        f"{phase}.failure.json": snapshot,
    }
    if payload is not None:
        artifacts[f"{phase}.failure.payload.json"] = payload
    return write_named_artifacts(runtime, step_id, artifacts)


def block_state(runtime: RuntimeContext, state: dict[str, Any], message: str) -> dict[str, Any]:
    node_id = runtime.current_node_id() or "unknown"
    runtime.log_node_event(
        step_id=node_id,
        event="blocked",
        message=message,
        detail={"reason": message},
        level="warning",
        node_id=node_id,
    )
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
    log_node_step(
        runtime,
        step_id=step_id,
        event="soft_failed",
        message=message,
        detail={
            "output": summarize_value(output),
            "artifact_count": len(artifacts or []),
        },
        level="warning",
    )
    return patch


def skip_if_blocked(state: dict[str, Any]) -> dict[str, Any] | None:
    if str(state.get("status", "")).strip().lower() == "blocked":
        return {}
    if state.get("errors"):
        return {}
    return None
