from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
            self.assertTrue((root / "var" / "runs" / "default" / "fake-flow" / "20260421190000" / "state.json").exists())


if __name__ == "__main__":
    unittest.main()
