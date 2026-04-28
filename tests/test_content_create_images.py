from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from workflow.integrations.image_generation import (
    build_generated_image_object_key,
    download_reference_image,
    edit_image,
    generate_images,
)
from workflow.integrations.s3 import S3UploadedObject
from workflow.runtime.tenant import TenantRuntimeConfig
from workflow.store import StoreError


class _FakeUploader:
    def __init__(self) -> None:
        self.url_calls: list[tuple[str, str]] = []
        self.byte_calls: list[tuple[bytes, str, str]] = []

    def upload_from_url(
        self,
        source_url: str,
        object_key: str,
        *,
        timeout: int = 300,
        content_type: str = "",
    ) -> S3UploadedObject:
        self.url_calls.append((source_url, object_key))
        suffix = Path(object_key).name
        return S3UploadedObject(
            bucket="assets",
            key=f"uploaded/{suffix}.png",
            url=f"https://cdn.example.com/{suffix}.png",
            etag='"etag"',
            content_type="image/png",
            size=12,
        )

    def upload_bytes(
        self,
        data: bytes,
        object_key: str,
        *,
        content_type: str = "application/octet-stream",
        timeout: int = 300,
    ) -> S3UploadedObject:
        self.byte_calls.append((data, object_key, content_type))
        suffix = Path(object_key).name
        return S3UploadedObject(
            bucket="assets",
            key=f"uploaded/{suffix}.png",
            url=f"https://cdn.example.com/{suffix}.png",
            etag='"etag"',
            content_type=content_type,
            size=len(data),
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
                    ["cover prompt", "detail prompt"],
                )

        cover_key = build_generated_image_object_key("run-001", 0, "cover prompt", 0)
        image_key = build_generated_image_object_key("run-001", 1, "detail prompt", 0)
        self.assertEqual(payload["cover_url"], f"https://cdn.example.com/{Path(cover_key).name}.png")
        self.assertEqual(payload["image_urls"], [f"https://cdn.example.com/{Path(image_key).name}.png"])
        self.assertEqual(payload["raw_results"][0]["provider"], "ark")
        self.assertEqual(payload["raw_results"][0]["urls"], ["https://ark.example.com/cover.png"])
        self.assertEqual(payload["raw_results"][1]["urls"], ["https://ark.example.com/detail.png"])
        self.assertEqual(payload["uploaded_results"][0]["uploaded"][0]["source_url"], "https://ark.example.com/cover.png")
        self.assertEqual(payload["uploaded_results"][1]["uploaded"][0]["source_url"], "https://ark.example.com/detail.png")
        self.assertEqual(
            uploader.url_calls,
            [
                ("https://ark.example.com/cover.png", cover_key),
                ("https://ark.example.com/detail.png", image_key),
            ],
        )

    def test_generate_images_raises_when_ark_api_key_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaisesRegex(StoreError, "ARK_API_KEY"):
                generate_images({"root": str(root), "step": {}, "batch_id": "run-001"}, ["prompt"])

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
                    ["cover prompt"],
                )

        request_ark_image.assert_called_once()
        self.assertEqual(payload["raw_results"][0]["provider"], "ark")

    def test_generate_images_supports_openai_provider_with_base64_upload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            uploader = _FakeUploader()
            sdk_result = SimpleNamespace(
                data=[SimpleNamespace(b64_json="aGVsbG8=", url=None, mime_type="image/png")]
            )

            with (
                patch(
                    "workflow.integrations.image_generation.request_openai_image",
                    return_value={
                        "created": 123,
                        "data": [{"has_b64_json": True, "mime_type": "image/png"}],
                        "_sdk_result": sdk_result,
                    },
                ) as request_openai_image,
                patch("workflow.integrations.image_generation.build_s3_uploader", return_value=uploader),
            ):
                payload = generate_images(
                    {
                        "root": str(root),
                        "step": {
                            "image_provider": "openai",
                            "image_model": "gpt-image-2",
                            "image_base_url": "https://api.uniapi.io/v1",
                        },
                        "batch_id": "run-003",
                        "tenant_config": TenantRuntimeConfig(
                            payload={
                                "api_mode": "custom",
                                "api_ref": {
                                    "OPENAI_IMAGE_API_KEY": "image-key",
                                    "OPENAI_IMAGE_BASE_URL": "https://api.uniapi.io/v1",
                                },
                            }
                        ),
                    },
                    ["cover prompt"],
                )

        request_openai_image.assert_called_once()
        cover_key = build_generated_image_object_key("run-003", 0, "cover prompt", 0)
        self.assertEqual(payload["cover_url"], f"https://cdn.example.com/{Path(cover_key).name}.png")
        self.assertEqual(payload["raw_results"][0]["provider"], "openai")
        self.assertEqual(payload["raw_results"][0]["sources"][0]["kind"], "bytes")
        self.assertEqual(uploader.byte_calls, [(b"hello", cover_key, "image/png")])

    def test_generate_images_uses_openai_edit_when_reference_images_are_provided(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            uploader = _FakeUploader()
            sdk_result = SimpleNamespace(
                data=[SimpleNamespace(b64_json="aGVsbG8=", url=None, mime_type="image/png")]
            )
            reference_images = [
                {
                    "source_url": "https://cdn.example.com/reference-1.png",
                    "filename": "reference-1.png",
                    "content_type": "image/png",
                    "data": b"first",
                },
                {
                    "source_url": "https://cdn.example.com/reference-2.png",
                    "filename": "reference-2.png",
                    "content_type": "image/png",
                    "data": b"second",
                },
            ]

            with (
                patch(
                    "workflow.integrations.image_generation.download_reference_image",
                    side_effect=reference_images,
                ) as download_reference_image,
                patch(
                    "workflow.integrations.image_generation.request_openai_image_edit",
                    return_value={
                        "created": 123,
                        "data": [{"has_b64_json": True, "mime_type": "image/png"}],
                        "_sdk_result": sdk_result,
                    },
                ) as request_openai_image_edit,
                patch(
                    "workflow.integrations.image_generation.request_openai_image",
                ) as request_openai_image,
                patch("workflow.integrations.image_generation.build_s3_uploader", return_value=uploader),
            ):
                payload = generate_images(
                    {
                        "root": str(root),
                        "step": {
                            "image_provider": "openai",
                            "image_model": "gpt-image-2",
                            "image_base_url": "https://api.uniapi.io/v1",
                        },
                        "batch_id": "run-003b",
                        "tenant_config": TenantRuntimeConfig(
                            payload={
                                "api_mode": "custom",
                                "api_ref": {
                                    "OPENAI_IMAGE_API_KEY": "image-key",
                                    "OPENAI_IMAGE_BASE_URL": "https://api.uniapi.io/v1",
                                },
                            }
                        ),
                    },
                    ["cover prompt"],
                    reference_image_urls=[
                        "https://cdn.example.com/reference-1.png",
                        "https://cdn.example.com/reference-2.png",
                    ],
                )

        request_openai_image_edit.assert_called_once()
        request_openai_image.assert_not_called()
        download_reference_image.assert_any_call("https://cdn.example.com/reference-1.png")
        download_reference_image.assert_any_call("https://cdn.example.com/reference-2.png")
        cover_key = build_generated_image_object_key("run-003b", 0, "cover prompt", 0)
        self.assertEqual(payload["cover_url"], f"https://cdn.example.com/{Path(cover_key).name}.png")
        self.assertEqual(payload["raw_results"][0]["provider"], "openai")
        self.assertEqual(payload["raw_results"][0]["reference_images"][0]["source_url"], "https://cdn.example.com/reference-1.png")
        self.assertEqual(uploader.byte_calls, [(b"hello", cover_key, "image/png")])

    def test_generate_images_rejects_unsupported_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaisesRegex(StoreError, "unsupported image provider"):
                generate_images(
                    {
                        "root": str(root),
                        "step": {"image_provider": "unsupported-provider"},
                        "batch_id": "run-004",
                    },
                    ["prompt"],
                )

    def test_edit_image_supports_openai_provider_with_reference_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            uploader = _FakeUploader()
            sdk_result = SimpleNamespace(
                data=[SimpleNamespace(b64_json="aGVsbG8=", url=None, mime_type="image/png")]
            )
            reference_images = [
                {
                    "source_url": "https://cdn.example.com/reference-1.png",
                    "filename": "reference-1.png",
                    "content_type": "image/png",
                    "data": b"first",
                },
                {
                    "source_url": "https://cdn.example.com/reference-2.png",
                    "filename": "reference-2.png",
                    "content_type": "image/png",
                    "data": b"second",
                },
            ]

            with (
                patch(
                    "workflow.integrations.image_generation.download_reference_image",
                    side_effect=reference_images,
                ) as download_reference_image,
                patch(
                    "workflow.integrations.image_generation.request_openai_image_edit",
                    return_value={
                        "created": 123,
                        "data": [{"has_b64_json": True, "mime_type": "image/png"}],
                        "_sdk_result": sdk_result,
                    },
                ) as request_openai_image_edit,
                patch("workflow.integrations.image_generation.build_s3_uploader", return_value=uploader),
            ):
                payload = edit_image(
                    {
                        "root": str(root),
                        "step": {
                            "image_provider": "openai",
                            "image_model": "gpt-image-2",
                            "image_base_url": "https://api.uniapi.io/v1",
                        },
                        "batch_id": "run-005",
                        "tenant_config": TenantRuntimeConfig(
                            payload={
                                "api_mode": "custom",
                                "api_ref": {
                                    "OPENAI_IMAGE_API_KEY": "image-key",
                                    "OPENAI_IMAGE_BASE_URL": "https://api.uniapi.io/v1",
                                },
                            }
                        ),
                    },
                    "edit prompt",
                    [
                        "https://cdn.example.com/reference-1.png",
                        "https://cdn.example.com/reference-2.png",
                    ],
                )

        request_openai_image_edit.assert_called_once()
        download_reference_image.assert_any_call("https://cdn.example.com/reference-1.png")
        download_reference_image.assert_any_call("https://cdn.example.com/reference-2.png")
        cover_key = build_generated_image_object_key("run-005", 0, "edit prompt", 0)
        self.assertEqual(payload["cover_url"], f"https://cdn.example.com/{Path(cover_key).name}.png")
        self.assertEqual(payload["raw_results"][0]["provider"], "openai")
        self.assertEqual(payload["raw_results"][0]["reference_images"][0]["source_url"], "https://cdn.example.com/reference-1.png")
        self.assertEqual(uploader.byte_calls, [(b"hello", cover_key, "image/png")])

    def test_download_reference_image_supports_data_urls(self) -> None:
        payload = download_reference_image("data:image/png;base64,aGVsbG8=")

        self.assertEqual(payload["source_url"], "data:image/png;base64,aGVsbG8=")
        self.assertEqual(payload["content_type"], "image/png")
        self.assertEqual(payload["filename"], "reference-image.png")
        self.assertEqual(payload["data"], b"hello")


if __name__ == "__main__":
    unittest.main()
