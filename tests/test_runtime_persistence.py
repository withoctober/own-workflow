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
            self.assertEqual(upsert_workflow_run.call_args.kwargs["current_node_index"], 0)
            self.assertEqual(upsert_workflow_run.call_args.kwargs["total_node_count"], 8)
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
            self.assertEqual(last_call["current_node_index"], 0)
            self.assertEqual(last_call["total_node_count"], 8)
            self.assertEqual(last_call["completed_node_count"], 1)
            self.assertEqual(last_call["error_count"], 0)
            self.assertEqual(last_call["last_message"], "all done")
            self.assertTrue(last_call["finished_at"])

    def test_mark_run_finished_does_not_duplicate_messages_after_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = WorkflowSettings.from_root(root)
            context = RuntimeContext(settings=settings, flow_id="content-create-original", batch_id="20260424151500", tenant_id="tenant-2")
            repository = StateRepository(context)

            repository.save(
                {
                    **context.base_state(),
                    "status": "running",
                    "completed_nodes": ["create-original-01-copy"],
                    "node_statuses": {
                        "create-original-01-copy": {
                            "status": "completed",
                            "message": "已生成原创文案",
                        }
                    },
                    "messages": ["已生成原创文案"],
                    "resume_count": 1,
                    "resumed_from_node": "create-original-02-images",
                }
            )

            final_state = repository.mark_run_finished(
                {
                    "flow_id": "content-create-original",
                    "tenant_id": "tenant-2",
                    "batch_id": "20260424151500",
                    "status": "running",
                    "current_node": "",
                    "completed_nodes": ["create-original-01-copy", "create-original-02-images"],
                    "node_statuses": {
                        "create-original-01-copy": {
                            "status": "completed",
                            "message": "已生成原创文案",
                        },
                        "create-original-02-images": {
                            "status": "completed",
                            "message": "已生成原创配图并写入作品库",
                        },
                    },
                    "messages": ["已生成原创文案", "已生成原创配图并写入作品库"],
                    "errors": [],
                    "outputs": {},
                    "artifacts": {},
                    "resume_count": 1,
                    "resumed_from_node": "create-original-02-images",
                }
            )

            self.assertEqual(
                final_state["messages"],
                ["已生成原创文案", "已生成原创配图并写入作品库"],
            )
            self.assertEqual(final_state["status"], "completed")

    def test_prepare_resume_clears_failed_node_residue(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = WorkflowSettings.from_root(root)
            context = RuntimeContext(settings=settings, flow_id="content-create-original", batch_id="20260424151500", tenant_id="tenant-2")
            repository = StateRepository(context)

            repository.save(
                {
                    **context.base_state(),
                    "status": "failed",
                    "current_node": "create-original-02-images",
                    "completed_nodes": ["create-original-01-copy"],
                    "node_statuses": {
                        "create-original-01-copy": {
                            "status": "completed",
                            "message": "已生成原创文案",
                        },
                        "unknown": {
                            "status": "failed",
                            "error": "Request timed out.",
                        },
                        "create-original-02-images": {
                            "status": "failed",
                            "error": "Request timed out.",
                        },
                    },
                    "messages": ["已生成原创文案"],
                    "errors": ["Request timed out."],
                }
            )

            resumed_state = repository.prepare_resume()

            self.assertEqual(resumed_state["status"], "running")
            self.assertEqual(resumed_state["resume_count"], 1)
            self.assertEqual(resumed_state["resumed_from_node"], "create-original-02-images")
            self.assertEqual(
                resumed_state["node_statuses"],
                {
                    "create-original-01-copy": {
                        "status": "completed",
                        "message": "已生成原创文案",
                    }
                },
            )
            self.assertEqual(resumed_state["errors"], [])


if __name__ == "__main__":
    unittest.main()
