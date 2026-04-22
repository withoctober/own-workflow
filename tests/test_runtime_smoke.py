from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow.flow.common import block_state, log_node_step
from workflow.runtime.engine import GraphRuntime, RunRequest
from workflow.runtime.tenant import TenantRuntimeConfig
from workflow.settings import WorkflowSettings


class GraphRuntimeSmokeTest(unittest.TestCase):
    def test_run_executes_compiled_graph_and_persists_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = GraphRuntime(WorkflowSettings.from_root(root))

            fake_flow = {
                "entrypoint": "step-01",
                "terminal": "step-01",
                "nodes": {
                    "step-01": lambda state: {
                        "messages": ["ok"],
                        "outputs": {"step-01": {"status": "done"}},
                    }
                },
                "edges": [],
            }

            with patch("workflow.runtime.engine.build_flow_definition", return_value=fake_flow):
                result = runtime.run(
                    RunRequest(
                        flow_id="fake-flow",
                        tenant_id="default",
                        batch_id="20260421190000",
                        tenant_runtime_config=TenantRuntimeConfig(payload={"tables": {}, "docs": {}}),
                    )
                )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["messages"][-1], "ok")
            self.assertEqual(result["outputs"]["step-01"]["status"], "done")
            run_root = root / "var" / "runs" / "default" / "fake-flow" / "20260421190000"
            self.assertTrue((run_root / "state.json").exists())
            events = [
                json.loads(line)
                for line in (run_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            event_types = [event["type"] for event in events]
            self.assertIn("run_started", event_types)
            self.assertIn("node_started", event_types)
            self.assertIn("node_finished", event_types)
            self.assertIn("run_finished", event_types)

    def test_run_persists_node_internal_events_for_blocked_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = GraphRuntime(WorkflowSettings.from_root(root))

            def blocked_node_factory(context):
                def node(state):
                    log_node_step(
                        context,
                        step_id="step-01",
                        event="input_loaded",
                        message="已读取测试输入",
                        detail={"records": 0},
                    )
                    return block_state(context, state, "缺少测试输入")

                return node

            fake_flow = {
                "entrypoint": "step-01",
                "terminal": "step-01",
                "nodes": {
                    "step-01": blocked_node_factory(runtime.build_context(
                        RunRequest(
                            flow_id="fake-flow",
                            tenant_id="default",
                            batch_id="20260421190001",
                            tenant_runtime_config=TenantRuntimeConfig(payload={"tables": {}, "docs": {}}),
                        )
                    ))
                },
                "edges": [],
            }

            with patch("workflow.runtime.engine.build_flow_definition", return_value=fake_flow):
                result = runtime.run(
                    RunRequest(
                        flow_id="fake-flow",
                        tenant_id="default",
                        batch_id="20260421190001",
                        tenant_runtime_config=TenantRuntimeConfig(payload={"tables": {}, "docs": {}}),
                    )
                )

            self.assertEqual(result["status"], "blocked")
            run_root = root / "var" / "runs" / "default" / "fake-flow" / "20260421190001"
            events = [
                json.loads(line)
                for line in (run_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            step_events = [event for event in events if event["type"] == "node_step"]
            self.assertTrue(step_events)
            self.assertTrue(any(event.get("event") == "input_loaded" for event in step_events))
            self.assertTrue(any(event.get("event") == "blocked" for event in step_events))


if __name__ == "__main__":
    unittest.main()
