from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow.integrations.image_generation import build_generated_image_object_key, generate_images
from workflow.integrations.s3 import S3UploadedObject
from workflow.runtime.tenant import TenantRuntimeConfig
from workflow.store import StoreError


class _FakeUploader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def upload_from_url(self, source_url: str, object_key: str, *, timeout: int = 300, content_type: str = "") -> S3UploadedObject:
        self.calls.append((source_url, object_key))
        suffix = Path(object_key).name
        return S3UploadedObject(
            bucket="assets",
            key=f"uploaded/{suffix}.png",
            url=f"https://cdn.example.com/{suffix}.png",
            etag='"etag"',
            content_type="image/png",
            size=12,
        )


class ContentCreateImagesTest(unittest.TestCase):
    def test_generate_images_uploads_generated_urls_to_s3(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text("ARK_API_KEY=ark-key\n", encoding="utf-8")
            uploader = _FakeUploader()

            with (
                patch(
                    "workflow.integrations.image_generation.request_ark_image",
                    side_effect=[
                        {"data": [{"url": "https://ark.example.com/cover.png"}]},
                        {"data": [{"url": "https://ark.example.com/detail.png"}]},
                    ],
                ),
                patch("workflow.integrations.image_generation.build_s3_uploader", return_value=uploader),
            ):
                payload = generate_images(
                    {
                        "root": str(root),
                        "batch_id": "run-001",
                        "step": {"image_model": "model-x", "image_size": "100x100"},
                        "tenant_config": TenantRuntimeConfig(payload={"api_mode": "system", "api_ref": {}}),
                    },
                    ["封面提示词", "配图提示词"],
                )

        cover_key = build_generated_image_object_key("run-001", 0, "封面提示词", 0)
        image_key = build_generated_image_object_key("run-001", 1, "配图提示词", 0)
        self.assertEqual(payload["cover_url"], f"https://cdn.example.com/{Path(cover_key).name}.png")
        self.assertEqual(payload["image_urls"], [f"https://cdn.example.com/{Path(image_key).name}.png"])
        self.assertEqual(payload["raw_results"][0]["provider"], "ark")
        self.assertEqual(payload["raw_results"][0]["urls"], ["https://ark.example.com/cover.png"])
        self.assertEqual(payload["raw_results"][1]["urls"], ["https://ark.example.com/detail.png"])
        self.assertEqual(payload["uploaded_results"][0]["uploaded"][0]["source_url"], "https://ark.example.com/cover.png")
        self.assertEqual(payload["uploaded_results"][1]["uploaded"][0]["source_url"], "https://ark.example.com/detail.png")
        self.assertEqual(
            uploader.calls,
            [
                ("https://ark.example.com/cover.png", cover_key),
                ("https://ark.example.com/detail.png", image_key),
            ],
        )

    def test_generate_images_raises_when_ark_api_key_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaisesRegex(StoreError, "ARK_API_KEY"):
                generate_images({"root": str(root), "step": {}, "batch_id": "run-001"}, ["提示词"])

    def test_generate_images_uses_custom_provider_from_tenant_api_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            uploader = _FakeUploader()

            with (
                patch(
                    "workflow.integrations.image_generation.request_ark_image",
                    return_value={"data": [{"url": "https://ark.example.com/cover.png"}]},
                ) as request_ark_image,
                patch("workflow.integrations.image_generation.build_s3_uploader", return_value=uploader),
            ):
                payload = generate_images(
                    {
                        "root": str(root),
                        "batch_id": "run-002",
                        "step": {},
                        "tenant_config": TenantRuntimeConfig(
                            payload={
                                "api_mode": "custom",
                                "api_ref": {
                                    "IMAGE_PROVIDER": "ark",
                                    "ARK_API_KEY": "tenant-ark-key",
                                },
                            }
                        ),
                    },
                    ["封面提示词"],
                )

        request_ark_image.assert_called_once()
        self.assertEqual(payload["raw_results"][0]["provider"], "ark")

    def test_generate_images_rejects_unsupported_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaisesRegex(StoreError, "不支持的图片 provider"):
                generate_images(
                    {
                        "root": str(root),
                        "step": {"image_provider": "openai"},
                        "batch_id": "run-003",
                    },
                    ["提示词"],
                )


if __name__ == "__main__":
    unittest.main()
