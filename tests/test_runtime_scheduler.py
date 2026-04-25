from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from model import TenantFlowSchedule
from workflow.runtime.engine import GraphRuntime
from workflow.runtime.scheduler import (
    TenantFlowScheduler,
    build_schedule_batch_id,
    compute_next_run_at,
    normalize_batch_id_prefix,
    validate_cron_expression,
)
from workflow.settings import WorkflowSettings


class RuntimeSchedulerTest(unittest.TestCase):
    def test_validate_cron_expression_accepts_and_rejects_expected_values(self) -> None:
        validate_cron_expression("*/15 * * * *")
        with self.assertRaises(ValueError):
            validate_cron_expression("* *")

    def test_compute_next_run_at_returns_next_matching_minute(self) -> None:
        after = datetime(2026, 4, 23, 6, 7, tzinfo=ZoneInfo("Asia/Shanghai"))
        next_run_at = compute_next_run_at("*/15 * * * *", after=after)
        self.assertEqual(next_run_at, datetime(2026, 4, 23, 6, 15, tzinfo=ZoneInfo("Asia/Shanghai")))

    def test_normalize_batch_id_prefix_and_batch_id_builder(self) -> None:
        schedule = TenantFlowSchedule(
            id="schedule-pk",
            tenant_pk="tenant-pk",
            tenant_id="tenant-a",
            flow_id="daily-report",
            cron_expr="0 * * * *",
            is_active=True,
            request_payload={},
            batch_id_prefix="Daily Report",
            next_run_at=None,
            last_run_at=None,
            last_status="",
            last_error="",
            last_batch_id="",
            is_running=False,
            locked_at=None,
            created_at=None,
            updated_at=None,
        )
        now = datetime(2026, 4, 23, 6, 30, 45, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertEqual(normalize_batch_id_prefix("Daily Report"), "daily-report")
        self.assertEqual(build_schedule_batch_id(schedule, now), "daily-report-20260423063045")

    def test_run_pending_claims_and_executes_due_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = WorkflowSettings.from_root(Path(tmpdir))
            runtime = GraphRuntime(settings)
            scheduler = TenantFlowScheduler(settings, runtime, poll_interval_seconds=0.1)
            due_schedule = TenantFlowSchedule(
                id="schedule-pk",
                tenant_pk="tenant-pk",
                tenant_id="tenant-a",
                flow_id="daily-report",
                cron_expr="*/15 * * * *",
                is_active=True,
                request_payload={"source_url": ""},
                batch_id_prefix="daily",
                next_run_at=datetime(2026, 4, 23, 6, 15, tzinfo=ZoneInfo("Asia/Shanghai")),
                last_run_at=None,
                last_status="",
                last_error="",
                last_batch_id="",
                is_running=False,
                locked_at=None,
                created_at=None,
                updated_at=None,
            )

            with (
                patch("workflow.runtime.scheduler.postgres_enabled", return_value=True),
                patch("workflow.runtime.scheduler.list_due_tenant_flow_schedules", return_value=[due_schedule]),
                patch("workflow.runtime.scheduler.claim_tenant_flow_schedule", return_value=due_schedule),
                patch(
                    "workflow.runtime.scheduler.get_tenant_runtime_config",
                    return_value={"tenant_id": "tenant-a", "tables": {}, "docs": {}, "timeout_seconds": 600, "max_retries": 2},
                ),
                patch("workflow.runtime.scheduler.has_flow_definition", return_value=True),
                patch("workflow.runtime.scheduler.GraphRuntime.run", return_value={"status": "completed"}) as runtime_run,
                patch("workflow.runtime.scheduler.complete_tenant_flow_schedule_run") as complete_schedule,
                patch(
                    "workflow.runtime.scheduler.now_in_schedule_timezone",
                    return_value=datetime(2026, 4, 23, 6, 15, tzinfo=ZoneInfo("Asia/Shanghai")),
                ),
            ):
                processed = scheduler.run_pending()

            self.assertEqual(processed, 1)
            runtime_run.assert_called_once()
            run_request = runtime_run.call_args.args[0]
            self.assertEqual(run_request.trigger_mode, "cron")
            complete_schedule.assert_called_once()
            self.assertEqual(complete_schedule.call_args.kwargs["last_status"], "completed")


if __name__ == "__main__":
    unittest.main()
