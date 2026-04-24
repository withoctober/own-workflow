"""Runtime package."""

from __future__ import annotations

from typing import Any


def TenantFlowScheduler(*args: Any, **kwargs: Any):
    from workflow.runtime.scheduler import TenantFlowScheduler as _TenantFlowScheduler

    return _TenantFlowScheduler(*args, **kwargs)


def compute_next_run_at(*args: Any, **kwargs: Any):
    from workflow.runtime.scheduler import compute_next_run_at as _compute_next_run_at

    return _compute_next_run_at(*args, **kwargs)


def validate_cron_expression(*args: Any, **kwargs: Any):
    from workflow.runtime.scheduler import validate_cron_expression as _validate_cron_expression

    return _validate_cron_expression(*args, **kwargs)


__all__ = ["TenantFlowScheduler", "compute_next_run_at", "validate_cron_expression"]
