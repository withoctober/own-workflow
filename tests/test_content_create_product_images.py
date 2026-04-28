from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from workflow.flow.content_create.nodes import original_images
from workflow.flow.content_create.utils import build_llm_safe_topic_context, extract_product_image_urls
from workflow.runtime.context import RuntimeContext
from workflow.runtime.tenant import TenantRuntimeConfig
from workflow.settings import WorkflowSettings


class ContentCreateProductImagesTest(unittest.TestCase):
    def test_extract_product_image_urls_parses_common_shapes(self) -> None:
        topic_context = {
            "source_dataset": "products",
            "product": {
                "\u4ea7\u54c1\u56fe\u7247": '[{"url":"https://cdn.example.com/a.png"},{"src":"https://cdn.example.com/b.png"}]',
                "image_urls": ["https://cdn.example.com/c.png", "https://cdn.example.com/a.png"],
                "\u56fe\u7247": "https://cdn.example.com/d.png,\nhttps://cdn.example.com/e.png",
                "product_images": ["data:image/png;base64,aGVsbG8="],
                "cover_image": "https://cdn.example.com/f.png",
            },
        }

        self.assertEqual(
            extract_product_image_urls(topic_context),
            [
                "https://cdn.example.com/a.png",
                "https://cdn.example.com/b.png",
                "https://cdn.example.com/d.png",
                "https://cdn.example.com/e.png",
                "https://cdn.example.com/c.png",
                "data:image/png;base64,aGVsbG8=",
                "https://cdn.example.com/f.png",
            ],
        )

    def test_original_images_passes_product_reference_images_to_image_generation(self) -> None:
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
                batch_id="20260428120000",
                tenant_id="tenant-a",
                source_url="",
                topic_context={
                    "source_dataset": "products",
                    "record_id": "product-1",
                    "title": "Product One",
                    "product": {
                        "\u4ea7\u54c1\u56fe\u7247": [
                            {"url": "https://cdn.example.com/product-1.png"},
                            {"image_url": "https://cdn.example.com/product-2.png"},
                        ]
                    },
                },
                tenant_runtime_config=TenantRuntimeConfig(
                    payload={
                        "tenant_id": "tenant-a",
                        "database_url": "postgresql://example",
                        "store_type": "database",
                    }
                ),
            )
            store = MagicMock()
            store.read_doc.return_value = "marketing-plan"
            store.read_table.return_value = [{"\u65e5\u671f": "2026-04-28", "\u4eca\u65e5\u9009\u9898": "topic"}]
            store.list_table_fields.return_value = [
                "\u751f\u6210\u65e5\u671f",
                "\u6807\u9898",
                "\u6b63\u6587",
                "\u6807\u7b7e",
                "\u5c01\u9762\u63d0\u793a\u8bcd",
                "\u5c01\u9762\u94fe\u63a5",
                "\u914d\u56fe\u63d0\u793a\u8bcd",
                "\u914d\u56fe\u94fe\u63a5",
                "\u62a5\u9519\u4fe1\u606f",
            ]
            state = {
                "outputs": {
                    "create-original-01-copy": {
                        "title": "Title",
                        "content": "Body #tag",
                        "tags": "#tag",
                    }
                }
            }

            prompt_result = type(
                "Result",
                (),
                {
                    "value": {
                        "cover_prompt": "cover prompt",
                        "image_prompts": ["detail prompt"],
                    },
                    "messages": ["ok"],
                },
            )()

            with (
                patch.object(runtime, "store", return_value=store),
                patch(
                    "workflow.flow.content_create.nodes.generate_original_image_prompts",
                    return_value=prompt_result,
                ) as generate_original_image_prompts_mock,
                patch(
                    "workflow.flow.content_create.nodes.generate_images",
                    return_value={
                        "cover_url": "https://cdn.example.com/cover.png",
                        "image_urls": ["https://cdn.example.com/1.png"],
                        "images": [],
                    },
                ) as generate_images_mock,
                patch(
                    "workflow.flow.content_create.nodes.upsert_artifact",
                    return_value=type(
                        "ArtifactStub",
                        (),
                        {
                            "id": "artifact-pk",
                            "title": "Title",
                            "artifact_type": "content",
                            "batch_id": "20260428120000",
                        },
                    )(),
                ),
            ):
                original_images(runtime)(state)

        self.assertNotIn("extra_text", generate_original_image_prompts_mock.call_args.kwargs)
        self.assertNotIn("extra_images", generate_original_image_prompts_mock.call_args.kwargs)
        self.assertEqual(
            generate_images_mock.call_args.kwargs["reference_image_urls"],
            [
                "https://cdn.example.com/product-1.png",
                "https://cdn.example.com/product-2.png",
            ],
        )

    def test_build_llm_safe_topic_context_removes_inline_image_fields(self) -> None:
        topic_context = {
            "source_dataset": "products",
            "record_id": "product-1",
            "title": "Product One",
            "product": {
                "name": "Product One",
                "产品图片": ["https://cdn.example.com/product-1.png"],
                "cover_image": "data:image/png;base64,aGVsbG8=",
                "image_urls": ["https://cdn.example.com/product-2.png"],
                "description": "Product description",
            },
        }

        safe_context = build_llm_safe_topic_context(topic_context)

        self.assertEqual(safe_context["product"]["name"], "Product One")
        self.assertEqual(safe_context["product"]["description"], "Product description")
        self.assertNotIn("产品图片", safe_context["product"])
        self.assertNotIn("cover_image", safe_context["product"])
        self.assertNotIn("image_urls", safe_context["product"])


if __name__ == "__main__":
    unittest.main()
