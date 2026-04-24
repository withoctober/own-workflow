from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from model import get_artifact, list_artifacts, upsert_artifact


class ArtifactModelTest(unittest.TestCase):
    @staticmethod
    def _artifact_row(*, artifact_id: str = "artifact-pk", batch_id: str = "batch-001") -> dict:
        return {
            "id": artifact_id,
            "tenant_id": "tenant-a",
            "flow_id": "content-create-original",
            "batch_id": batch_id,
            "workflow_run_id": batch_id,
            "artifact_type": "content",
            "title": "标题",
            "content": "正文",
            "tags": "#标签",
            "cover_prompt": "封面提示词",
            "cover_url": "https://cdn.example.com/cover.png",
            "image_prompts": ["图1", "图2"],
            "image_urls": ["https://cdn.example.com/1.png", "https://cdn.example.com/2.png"],
            "source_url": "https://example.com/source",
            "payload": {"copy": {"title": "标题"}},
            "created_at": None,
            "updated_at": None,
        }

    def test_upsert_artifact_insert_statement_matches_parameters(self) -> None:
        mock_cursor = MagicMock()
        mock_connection = MagicMock()
        mock_connection.__enter__.return_value = mock_connection
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = self._artifact_row()

        with patch("model.artifact.connect_postgres", return_value=mock_connection):
            artifact = upsert_artifact(
                "postgresql://example",
                tenant_id="tenant-a",
                flow_id="content-create-original",
                batch_id="batch-001",
                title="标题",
                content="正文",
                tags="#标签",
                cover_prompt="封面提示词",
                cover_url="https://cdn.example.com/cover.png",
                image_prompts=["图1", "图2"],
                image_urls=["https://cdn.example.com/1.png", "https://cdn.example.com/2.png"],
                payload={"copy": {"title": "标题"}},
            )

        self.assertEqual(artifact.batch_id, "batch-001")
        self.assertEqual(artifact.image_prompts, ["图1", "图2"])
        execute_args = mock_cursor.execute.call_args.args
        sql, params = execute_args
        self.assertIn("insert into artifacts", str(sql))
        self.assertEqual(params[0], "tenant-a")
        self.assertEqual(params[1], "content-create-original")
        self.assertEqual(params[2], "batch-001")
        mock_connection.commit.assert_called_once()

    def test_get_artifact_returns_single_item(self) -> None:
        mock_cursor = MagicMock()
        mock_connection = MagicMock()
        mock_connection.__enter__.return_value = mock_connection
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = self._artifact_row()

        with patch("model.artifact.connect_postgres", return_value=mock_connection):
            artifact = get_artifact("postgresql://example", tenant_id="tenant-a", artifact_id="artifact-pk")

        assert artifact is not None
        self.assertEqual(artifact.id, "artifact-pk")
        self.assertEqual(artifact.title, "标题")

    def test_list_artifacts_returns_items_and_total(self) -> None:
        mock_cursor = MagicMock()
        mock_connection = MagicMock()
        mock_connection.__enter__.return_value = mock_connection
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"total": 1}
        mock_cursor.fetchall.return_value = [self._artifact_row()]

        with patch("model.artifact.connect_postgres", return_value=mock_connection):
            items, total = list_artifacts(
                "postgresql://example",
                tenant_id="tenant-a",
                flow_id="content-create-original",
                limit=10,
                offset=0,
            )

        self.assertEqual(total, 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].flow_id, "content-create-original")
