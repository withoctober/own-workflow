from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow.runtime.context import RuntimeContext
from workflow.runtime.persistence import StateRepository
from workflow.settings import WorkflowSettings


class StateRepositoryPersistenceTest(unittest.TestCase):
    def test_mark_run_started_syncs_database_metadata_when_database_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = WorkflowSettings.from_root(root)
            settings.database_url = "postgresql://example"
            context = RuntimeContext(settings=settings, flow_id="content-collect", batch_id="20260423210000", tenant_id="tenant-2")
            repository = StateRepository(context)

            with patch("workflow.runtime.persistence.upsert_workflow_run") as upsert_workflow_run:
                state = repository.mark_run_started()

            self.assertEqual(state["status"], "running")
            upsert_workflow_run.assert_called_once()
            self.assertEqual(upsert_workflow_run.call_args.kwargs["tenant_id"], "tenant-2")
            self.assertEqual(upsert_workflow_run.call_args.kwargs["flow_id"], "content-collect")
            self.assertEqual(upsert_workflow_run.call_args.kwargs["batch_id"], "20260423210000")
            self.assertEqual(upsert_workflow_run.call_args.kwargs["status"], "running")
            self.assertEqual(upsert_workflow_run.call_args.kwargs["completed_node_count"], 0)
            self.assertEqual(upsert_workflow_run.call_args.kwargs["error_count"], 0)

    def test_mark_run_finished_syncs_summary_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = WorkflowSettings.from_root(root)
            settings.database_url = "postgresql://example"
            context = RuntimeContext(settings=settings, flow_id="content-collect", batch_id="20260423210100", tenant_id="tenant-2")
            repository = StateRepository(context)

            with patch("workflow.runtime.persistence.upsert_workflow_run") as upsert_workflow_run:
                repository.mark_run_started()
                repository.mark_node_started("collect-01")
                repository.mark_node_finished("collect-01", {"messages": ["done"]}, 20)
                final_state = repository.mark_run_finished({"messages": ["all done"]})

            self.assertEqual(final_state["status"], "completed")
            last_call = upsert_workflow_run.call_args.kwargs
            self.assertEqual(last_call["status"], "completed")
            self.assertEqual(last_call["completed_node_count"], 1)
            self.assertEqual(last_call["error_count"], 0)
            self.assertEqual(last_call["last_message"], "all done")
            self.assertTrue(last_call["finished_at"])


if __name__ == "__main__":
    unittest.main()
