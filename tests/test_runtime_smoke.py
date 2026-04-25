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
            state = json.loads((run_root / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["trigger_mode"], "")
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

    def test_resume_retries_from_failed_node_without_rerunning_completed_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = GraphRuntime(WorkflowSettings.from_root(root))
            calls: list[str] = []
            fail_once = {"done": False}

            def step_01(_: dict[str, object]) -> dict[str, object]:
                calls.append("step-01")
                return {
                    "messages": ["step-01 ok"],
                    "outputs": {"step-01": {"status": "done"}},
                }

            def step_02(_: dict[str, object]) -> dict[str, object]:
                calls.append("step-02")
                if not fail_once["done"]:
                    fail_once["done"] = True
                    raise RuntimeError("boom")
                return {
                    "messages": ["step-02 ok"],
                    "outputs": {"step-02": {"status": "done"}},
                }

            fake_flow = {
                "entrypoint": "step-01",
                "terminal": "step-02",
                "nodes": {"step-01": step_01, "step-02": step_02},
                "edges": [("step-01", "step-02")],
            }

            request = RunRequest(
                flow_id="fake-flow",
                tenant_id="default",
                batch_id="20260423071500",
                trigger_mode="manual",
                tenant_runtime_config=TenantRuntimeConfig(payload={"tables": {}, "docs": {}}),
            )

            with patch("workflow.runtime.engine.build_flow_definition", return_value=fake_flow):
                with self.assertRaises(RuntimeError):
                    runtime.run(request)
                result = runtime.resume(request)

            self.assertEqual(result["status"], "completed")
            self.assertEqual(calls, ["step-01", "step-02", "step-02"])
            self.assertEqual(result["resume_count"], 1)
            self.assertEqual(result["resumed_from_node"], "step-02")
            self.assertEqual(result["trigger_mode"], "manual")
            run_root = root / "var" / "runs" / "default" / "fake-flow" / "20260423071500"
            events = [
                json.loads(line)
                for line in (run_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            event_types = [event["type"] for event in events]
            self.assertIn("run_resumed", event_types)
            self.assertIn("node_skipped", event_types)

    def test_resume_clears_checkpoint_state_before_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = GraphRuntime(WorkflowSettings.from_root(root))
            calls: list[str] = []
            fail_once = {"done": False}

            def step_01(_: dict[str, object]) -> dict[str, object]:
                calls.append("step-01")
                return {
                    "messages": ["step-01 ok"],
                    "outputs": {"step-01": {"status": "done"}},
                }

            def step_02(state: dict[str, object]) -> dict[str, object]:
                calls.append(f"step-02-errors-{bool(state.get('errors'))}")
                if state.get("errors"):
                    return {}
                if not fail_once["done"]:
                    fail_once["done"] = True
                    raise RuntimeError("boom")
                return {
                    "messages": ["step-02 ok"],
                    "outputs": {"step-02": {"status": "done"}},
                }

            fake_flow = {
                "entrypoint": "step-01",
                "terminal": "step-02",
                "nodes": {"step-01": step_01, "step-02": step_02},
                "edges": [("step-01", "step-02")],
            }

            request = RunRequest(
                flow_id="fake-flow",
                tenant_id="default",
                batch_id="20260423071600",
                trigger_mode="manual",
                tenant_runtime_config=TenantRuntimeConfig(payload={"tables": {}, "docs": {}}),
            )

            with patch("workflow.runtime.engine.build_flow_definition", return_value=fake_flow):
                with self.assertRaises(RuntimeError):
                    runtime.run(request)
                result = runtime.resume(request)

            self.assertEqual(result["status"], "completed")
            self.assertEqual(calls, ["step-01", "step-02-errors-False", "step-02-errors-False"])


if __name__ == "__main__":
    unittest.main()
