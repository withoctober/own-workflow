from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from workflow.flow.content_create.nodes import original_images
from workflow.runtime.context import RuntimeContext
from workflow.runtime.tenant import TenantRuntimeConfig
from workflow.settings import WorkflowSettings


class ContentCreateArtifactWriteTest(unittest.TestCase):
    def test_original_images_writes_artifact_after_generating_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = WorkflowSettings(
                root=root,
                config_dir=root / "config",
                run_dir=root / "var" / "runs",
                database_url="postgresql://example",
                schedule_poll_interval_seconds=15,
                schedule_stale_lock_seconds=600,
            )
            runtime = RuntimeContext(
                settings=settings,
                flow_id="content-create-original",
                batch_id="20260424160000",
                tenant_id="tenant-a",
                source_url="",
                tenant_runtime_config=TenantRuntimeConfig(
                    payload={
                        "tenant_id": "tenant-a",
                        "database_url": "postgresql://example",
                        "store_type": "database",
                    }
                ),
            )
            store = MagicMock()
            store.read_doc.return_value = "营销方案"
            store.read_table.return_value = [{"日期": "2026-04-24", "今日选题": "主题"}]
            store.list_table_fields.return_value = ["生成日期", "标题", "正文", "标签", "封面提示词", "封面链接", "配图提示词", "配图链接", "报错信息"]

            state = {
                "outputs": {
                    "create-original-01-copy": {"title": "标题", "content": "正文 #标签", "tags": "#标签"},
                }
            }

            with (
                patch.object(runtime, "store", return_value=store),
                patch(
                    "workflow.flow.content_create.nodes.generate_original_image_prompts",
                    return_value=type("Result", (), {"value": {"cover_prompt": "封面提示词", "image_prompts": ["配图提示词"]}, "messages": ["ok"]})(),
                ),
                patch(
                    "workflow.flow.content_create.nodes.generate_images",
                    return_value={"cover_url": "https://cdn.example.com/cover.png", "image_urls": ["https://cdn.example.com/1.png"], "images": []},
                ),
                patch(
                    "workflow.flow.content_create.nodes.upsert_artifact",
                    return_value=type("ArtifactStub", (), {"id": "artifact-pk", "title": "标题", "artifact_type": "content", "batch_id": "20260424160000"})(),
                ) as upsert_artifact,
            ):
                result = original_images(runtime)(state)

        self.assertIn("create-original-02-images", result["outputs"])
        output = result["outputs"]["create-original-02-images"]
        self.assertEqual(output["artifact"]["artifact_id"], "artifact-pk")
        store.write_table.assert_called_once()
        upsert_artifact.assert_called_once()
        self.assertEqual(upsert_artifact.call_args.kwargs["tenant_id"], "tenant-a")
        self.assertEqual(upsert_artifact.call_args.kwargs["flow_id"], "content-create-original")
        self.assertEqual(upsert_artifact.call_args.kwargs["batch_id"], "20260424160000")
