from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from workflow.flow.common import write_failure_snapshot, write_stage_snapshot
from workflow.runtime.context import RuntimeContext
from workflow.runtime.tenant import TenantRuntimeConfig
from workflow.settings import WorkflowSettings


class FlowCommonLoggingTest(unittest.TestCase):
    def _runtime(self, root: Path) -> RuntimeContext:
        return RuntimeContext(
            settings=WorkflowSettings.from_root(root),
            flow_id="test-flow",
            batch_id="20260422233000",
            tenant_id="default",
            tenant_runtime_config=TenantRuntimeConfig(payload={"tables": {}, "docs": {}}),
        )

    def test_write_stage_snapshot_writes_detail_and_payload_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = self._runtime(root)

            artifacts = write_stage_snapshot(
                runtime,
                step_id="step-01",
                phase="generation",
                detail={"keys": ["title", "content"]},
                payload={"title": "T", "content": "C"},
            )

            self.assertEqual(len(artifacts), 2)
            detail_path = runtime.artifacts_dir / "step-01" / "generation.detail.json"
            payload_path = runtime.artifacts_dir / "step-01" / "generation.payload.json"
            self.assertTrue(detail_path.exists())
            self.assertTrue(payload_path.exists())
            self.assertEqual(json.loads(detail_path.read_text(encoding="utf-8")), {"keys": ["title", "content"]})
            self.assertEqual(json.loads(payload_path.read_text(encoding="utf-8")), {"title": "T", "content": "C"})

    def test_write_failure_snapshot_writes_failure_metadata_and_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = self._runtime(root)

            artifacts = write_failure_snapshot(
                runtime,
                step_id="step-02",
                phase="store_write",
                error="写入失败",
                detail={"row_count": 1},
                payload={"record": {"标题": "示例"}},
            )

            self.assertEqual(len(artifacts), 2)
            failure_path = runtime.artifacts_dir / "step-02" / "store_write.failure.json"
            payload_path = runtime.artifacts_dir / "step-02" / "store_write.failure.payload.json"
            self.assertTrue(failure_path.exists())
            self.assertTrue(payload_path.exists())
            self.assertEqual(
                json.loads(failure_path.read_text(encoding="utf-8")),
                {
                    "phase": "store_write",
                    "error": "写入失败",
                    "detail": {"row_count": 1},
                },
            )
            self.assertEqual(
                json.loads(payload_path.read_text(encoding="utf-8")),
                {"record": {"标题": "示例"}},
            )


if __name__ == "__main__":
    unittest.main()
