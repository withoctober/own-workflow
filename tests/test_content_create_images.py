from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from workflow.integrations.image_generation import (
    ImageProviderConfig,
    build_generated_image_object_key,
    build_image_payload,
    download_reference_image,
    edit_image,
    generate_images,
    request_uni_image_edit,
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
            (root / ".env").write_text(
                "IMAGE_PROVIDER=ark\nIMAGE_API_BASE_URL=https://ark.example.com/api/v3\nIMAGE_API_KEY=ark-key\nIMAGE_API_MODEL=model-x\n",
                encoding="utf-8",
            )
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
                        "step": {"image_size": "100x100"},
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

    def test_generate_images_passes_ark_reference_urls_as_image_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "IMAGE_PROVIDER=ark\nIMAGE_API_BASE_URL=https://ark.example.com/api/v3\nIMAGE_API_KEY=ark-key\nIMAGE_API_MODEL=model-x\n",
                encoding="utf-8",
            )
            uploader = _FakeUploader()

            with (
                patch(
                    "workflow.integrations.image_generation.request_ark_image",
                    return_value={"data": [{"url": "https://ark.example.com/edited.png"}]},
                ) as request_ark_image,
                patch(
                    "workflow.integrations.image_generation.download_reference_image",
                ) as download_reference_image,
                patch("workflow.integrations.image_generation.build_s3_uploader", return_value=uploader),
            ):
                payload = generate_images(
                    {
                        "root": str(root),
                        "batch_id": "run-001b",
                        "step": {"image_size": "100x100"},
                        "tenant_config": TenantRuntimeConfig(payload={"api_mode": "system", "api_ref": {}}),
                    },
                    ["edit prompt"],
                    reference_image_urls=[
                        "https://cdn.example.com/reference-1.png",
                        "https://cdn.example.com/reference-2.png",
                        "https://cdn.example.com/reference-1.png",
                    ],
                )

        request_ark_image.assert_called_once()
        self.assertEqual(
            request_ark_image.call_args.args[2]["image"],
            [
                "https://cdn.example.com/reference-1.png",
                "https://cdn.example.com/reference-2.png",
            ],
        )
        download_reference_image.assert_not_called()
        self.assertEqual(payload["raw_results"][0]["provider"], "ark")
        self.assertEqual(
            payload["raw_results"][0]["reference_images"],
            [
                {"source_url": "https://cdn.example.com/reference-1.png"},
                {"source_url": "https://cdn.example.com/reference-2.png"},
            ],
        )

    def test_build_image_payload_uses_scalar_ark_image_for_single_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "IMAGE_PROVIDER=ark\nIMAGE_API_BASE_URL=https://ark.example.com/api/v3\nIMAGE_API_KEY=ark-key\nIMAGE_API_MODEL=model-x\n",
                encoding="utf-8",
            )

            payload = build_image_payload(
                {"root": str(root), "step": {}},
                "edit prompt",
                ImageProviderConfig("ark", "https://ark.example.com/api/v3", "ark-key", "model-x"),
                ["https://cdn.example.com/reference.png"],
            )

        self.assertEqual(payload["image"], "https://cdn.example.com/reference.png")

    def test_build_image_payload_rejects_too_many_ark_reference_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "IMAGE_PROVIDER=ark\nIMAGE_API_BASE_URL=https://ark.example.com/api/v3\nIMAGE_API_KEY=ark-key\nIMAGE_API_MODEL=model-x\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(StoreError, "at most 14 reference images"):
                build_image_payload(
                    {"root": str(root), "step": {}},
                    "edit prompt",
                    ImageProviderConfig("ark", "https://ark.example.com/api/v3", "ark-key", "model-x"),
                    [f"https://cdn.example.com/reference-{index}.png" for index in range(15)],
                )

    def test_generate_images_requires_image_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "IMAGE_API_BASE_URL=https://ark.example.com/api/v3\nIMAGE_API_KEY=ark-key\nIMAGE_API_MODEL=model-x\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(StoreError, "IMAGE_PROVIDER"):
                generate_images({"root": str(root), "step": {}, "batch_id": "run-missing"}, ["prompt"])

    def test_generate_images_requires_image_base_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "IMAGE_PROVIDER=ark\nIMAGE_API_KEY=ark-key\nIMAGE_API_MODEL=model-x\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(StoreError, "IMAGE_API_BASE_URL"):
                generate_images({"root": str(root), "step": {}, "batch_id": "run-missing"}, ["prompt"])

    def test_generate_images_requires_image_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "IMAGE_PROVIDER=ark\nIMAGE_API_BASE_URL=https://ark.example.com/api/v3\nIMAGE_API_KEY=ark-key\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(StoreError, "IMAGE_API_MODEL"):
                generate_images({"root": str(root), "step": {}, "batch_id": "run-missing"}, ["prompt"])

    def test_generate_images_raises_when_ark_api_key_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "IMAGE_PROVIDER=ark\nIMAGE_API_BASE_URL=https://ark.example.com/api/v3\nIMAGE_API_MODEL=model-x\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(StoreError, "IMAGE_API_KEY"):
                generate_images({"root": str(root), "step": {}, "batch_id": "run-001"}, ["prompt"])

    def test_generate_images_rejects_empty_prompts_before_remote_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "IMAGE_PROVIDER=uni\nIMAGE_API_BASE_URL=https://api.uniapi.io/v1\nIMAGE_API_KEY=image-key\nIMAGE_API_MODEL=gpt-image-2\n",
                encoding="utf-8",
            )
            with (
                patch("workflow.integrations.image_generation.request_uni_image") as request_uni_image,
                self.assertRaisesRegex(StoreError, "image generation prompt at index 0 is empty"),
            ):
                generate_images({"root": str(root), "step": {}, "batch_id": "run-empty"}, ["", "   "])

        request_uni_image.assert_not_called()

    def test_generate_images_rejects_empty_prompt_without_shifting_image_slots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "IMAGE_PROVIDER=uni\nIMAGE_API_BASE_URL=https://api.uniapi.io/v1\nIMAGE_API_KEY=image-key\nIMAGE_API_MODEL=gpt-image-2\n",
                encoding="utf-8",
            )
            with (
                patch("workflow.integrations.image_generation.request_uni_image") as request_uni_image,
                self.assertRaisesRegex(StoreError, "image generation prompt at index 1 is empty"),
            ):
                generate_images({"root": str(root), "step": {}, "batch_id": "run-empty"}, ["cover prompt", "   "])

        request_uni_image.assert_not_called()

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
                                    "IMAGE_API_BASE_URL": "https://ark.example.com/api/v3",
                                    "IMAGE_API_KEY": "tenant-ark-key",
                                    "IMAGE_API_MODEL": "model-x",
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
                            "image_size": "1024x1024",
                        },
                        "batch_id": "run-003",
                        "tenant_config": TenantRuntimeConfig(
                            payload={
                                "api_mode": "custom",
                                "api_ref": {
                                    "IMAGE_PROVIDER": "openai",
                                    "IMAGE_API_KEY": "image-key",
                                    "IMAGE_API_BASE_URL": "https://api.uniapi.io/v1",
                                    "IMAGE_API_MODEL": "gpt-image-2",
                                },
                            }
                        ),
                    },
                    ["cover prompt"],
                )

        request_openai_image.assert_called_once()
        self.assertEqual(request_openai_image.call_args.args[0], "image-key")
        self.assertEqual(request_openai_image.call_args.args[1], "https://api.uniapi.io/v1")
        self.assertEqual(request_openai_image.call_args.args[2]["model"], "gpt-image-2")
        self.assertEqual(request_openai_image.call_args.args[2]["size"], "1024x1024")
        cover_key = build_generated_image_object_key("run-003", 0, "cover prompt", 0)
        self.assertEqual(payload["cover_url"], f"https://cdn.example.com/{Path(cover_key).name}.png")
        self.assertEqual(payload["raw_results"][0]["provider"], "openai")
        self.assertEqual(payload["raw_results"][0]["sources"][0]["kind"], "bytes")
        self.assertEqual(uploader.byte_calls, [(b"hello", cover_key, "image/png")])

    def test_generate_images_supports_openai_legacy_env_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "IMAGE_PROVIDER=openai\nOPENAI_IMAGE_API_KEY=image-key\nOPENAI_IMAGE_BASE_URL=https://api.uniapi.io/v1\nOPENAI_IMAGE_MODEL=gpt-image-2\n",
                encoding="utf-8",
            )
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
                        "step": {},
                        "batch_id": "run-003-legacy",
                        "tenant_config": TenantRuntimeConfig(payload={"api_mode": "system", "api_ref": {}}),
                    },
                    ["cover prompt"],
                )

        request_openai_image.assert_called_once()
        self.assertEqual(request_openai_image.call_args.args[0], "image-key")
        self.assertEqual(request_openai_image.call_args.args[1], "https://api.uniapi.io/v1")
        self.assertEqual(request_openai_image.call_args.args[2]["model"], "gpt-image-2")
        self.assertEqual(payload["raw_results"][0]["provider"], "openai")

    def test_generate_images_run_override_can_switch_to_ark(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "IMAGE_PROVIDER=openai\nOPENAI_IMAGE_API_KEY=image-key\nARK_API_KEY=ark-key\n",
                encoding="utf-8",
            )
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
                        "step": {},
                        "batch_id": "run-ark-override",
                        "tenant_config": TenantRuntimeConfig(
                            payload={
                                "api_mode": "system",
                                "api_ref": {},
                                "run_overrides": {
                                    "IMAGE_PROVIDER": "ark",
                                },
                            }
                        ),
                    },
                    ["cover prompt"],
                )

        request_ark_image.assert_called_once()
        self.assertEqual(request_ark_image.call_args.args[0], "ark-key")
        self.assertEqual(request_ark_image.call_args.args[1], "https://ark.cn-beijing.volces.com/api/v3")
        self.assertEqual(request_ark_image.call_args.args[2]["model"], "doubao-seedream-5-0-260128")
        self.assertEqual(payload["raw_results"][0]["provider"], "ark")

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
                        "step": {},
                        "batch_id": "run-003b",
                        "tenant_config": TenantRuntimeConfig(
                            payload={
                                "api_mode": "custom",
                                "api_ref": {
                                    "IMAGE_PROVIDER": "openai",
                                    "IMAGE_API_KEY": "image-key",
                                    "IMAGE_API_BASE_URL": "https://api.uniapi.io/v1",
                                    "IMAGE_API_MODEL": "gpt-image-2",
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

    def test_generate_images_supports_uni_provider_with_base64_upload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            uploader = _FakeUploader()

            with (
                patch(
                    "workflow.integrations.image_generation.request_uni_image",
                    return_value={
                        "created": 123,
                        "data": [{"has_b64_json": True, "mime_type": "image/png"}],
                        "_raw_data": [{"b64_json": "aGVsbG8=", "mime_type": "image/png"}],
                    },
                ) as request_uni_image,
                patch("workflow.integrations.image_generation.build_s3_uploader", return_value=uploader),
            ):
                payload = generate_images(
                    {
                        "root": str(root),
                        "step": {},
                        "batch_id": "run-003c",
                        "tenant_config": TenantRuntimeConfig(
                            payload={
                                "api_mode": "custom",
                                "api_ref": {
                                    "IMAGE_PROVIDER": "uni",
                                    "IMAGE_API_KEY": "image-key",
                                    "IMAGE_API_BASE_URL": "https://api.uniapi.io/v1",
                                    "IMAGE_API_MODEL": "gpt-image-2",
                                },
                            }
                        ),
                    },
                    ["cover prompt"],
                )

        request_uni_image.assert_called_once()
        self.assertEqual(request_uni_image.call_args.args[0], "image-key")
        self.assertEqual(request_uni_image.call_args.args[1], "https://api.uniapi.io/v1")
        self.assertEqual(request_uni_image.call_args.args[2], {"model": "gpt-image-2", "prompt": "cover prompt"})
        cover_key = build_generated_image_object_key("run-003c", 0, "cover prompt", 0)
        self.assertEqual(payload["cover_url"], f"https://cdn.example.com/{Path(cover_key).name}.png")
        self.assertEqual(payload["raw_results"][0]["provider"], "uni")
        self.assertEqual(payload["raw_results"][0]["sources"][0]["kind"], "bytes")
        self.assertEqual(uploader.byte_calls, [(b"hello", cover_key, "image/png")])

    def test_generate_images_uses_uni_edit_when_reference_images_are_provided(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            uploader = _FakeUploader()
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
                    "workflow.integrations.image_generation.request_uni_image_edit",
                    return_value={
                        "created": 123,
                        "data": [{"has_b64_json": True, "mime_type": "image/png"}],
                        "_raw_data": [{"b64_json": "aGVsbG8=", "mime_type": "image/png"}],
                    },
                ) as request_uni_image_edit,
                patch(
                    "workflow.integrations.image_generation.request_uni_image",
                ) as request_uni_image,
                patch("workflow.integrations.image_generation.build_s3_uploader", return_value=uploader),
            ):
                payload = generate_images(
                    {
                        "root": str(root),
                        "step": {},
                        "batch_id": "run-003d",
                        "tenant_config": TenantRuntimeConfig(
                            payload={
                                "api_mode": "custom",
                                "api_ref": {
                                    "IMAGE_PROVIDER": "uni",
                                    "IMAGE_API_KEY": "image-key",
                                    "IMAGE_API_BASE_URL": "https://api.uniapi.io/v1",
                                    "IMAGE_API_MODEL": "gpt-image-2",
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

        request_uni_image_edit.assert_called_once()
        request_uni_image.assert_not_called()
        download_reference_image.assert_any_call("https://cdn.example.com/reference-1.png")
        download_reference_image.assert_any_call("https://cdn.example.com/reference-2.png")
        self.assertEqual(request_uni_image_edit.call_args.args[1], "https://api.uniapi.io/v1")
        self.assertEqual(request_uni_image_edit.call_args.args[2], {"model": "gpt-image-2", "prompt": "cover prompt"})
        cover_key = build_generated_image_object_key("run-003d", 0, "cover prompt", 0)
        self.assertEqual(payload["cover_url"], f"https://cdn.example.com/{Path(cover_key).name}.png")
        self.assertEqual(payload["raw_results"][0]["provider"], "uni")
        self.assertEqual(payload["raw_results"][0]["reference_images"][0]["source_url"], "https://cdn.example.com/reference-1.png")
        self.assertEqual(uploader.byte_calls, [(b"hello", cover_key, "image/png")])

    def test_request_uni_image_edit_uses_image_array_multipart_fields(self) -> None:
        captured: dict[str, object] = {}

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback) -> None:
                return None

            def read(self) -> bytes:
                return b'{"created":123,"data":[{"b64_json":"aGVsbG8="}]}'

        def fake_urlopen(request_obj, timeout):
            captured["url"] = request_obj.full_url
            captured["timeout"] = timeout
            captured["headers"] = dict(request_obj.header_items())
            captured["body"] = request_obj.data
            return _FakeResponse()

        with patch("workflow.integrations.image_generation.urllib.request.urlopen", side_effect=fake_urlopen):
            response = request_uni_image_edit(
                "image-key",
                "https://api.uniapi.io/v1",
                {"model": "gpt-image-2", "prompt": "edit prompt"},
                [
                    {"filename": "first.png", "content_type": "image/png", "data": b"first"},
                    {"filename": "second.png", "content_type": "image/png", "data": b"second"},
                ],
            )

        body = bytes(captured["body"])
        self.assertEqual(captured["url"], "https://api.uniapi.io/v1/images/edits")
        self.assertIn(b'name="model"', body)
        self.assertIn(b"gpt-image-2", body)
        self.assertIn(b'name="prompt"', body)
        self.assertIn(b"edit prompt", body)
        self.assertEqual(body.count(b'name="image[]"'), 2)
        self.assertIn(b'filename="first.png"', body)
        self.assertIn(b'filename="second.png"', body)
        self.assertEqual(response["data"], [{"has_b64_json": True}])

    def test_generate_images_rejects_unsupported_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaisesRegex(StoreError, "unsupported image provider"):
                generate_images(
                    {
                        "root": str(root),
                        "step": {},
                        "batch_id": "run-004",
                        "tenant_config": TenantRuntimeConfig(
                            payload={
                                "api_mode": "custom",
                                "api_ref": {
                                    "IMAGE_PROVIDER": "unsupported-provider",
                                    "IMAGE_API_KEY": "image-key",
                                },
                            }
                        ),
                    },
                    ["prompt"],
                )

    def test_edit_image_supports_ark_provider_with_reference_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            uploader = _FakeUploader()

            with (
                patch(
                    "workflow.integrations.image_generation.request_ark_image",
                    return_value={"data": [{"url": "https://ark.example.com/edited.png"}]},
                ) as request_ark_image,
                patch(
                    "workflow.integrations.image_generation.download_reference_image",
                ) as download_reference_image,
                patch("workflow.integrations.image_generation.build_s3_uploader", return_value=uploader),
            ):
                payload = edit_image(
                    {
                        "root": str(root),
                        "step": {"image_size": "100x100"},
                        "batch_id": "run-004b",
                        "tenant_config": TenantRuntimeConfig(
                            payload={
                                "api_mode": "custom",
                                "api_ref": {
                                    "IMAGE_PROVIDER": "ark",
                                    "IMAGE_API_BASE_URL": "https://ark.example.com/api/v3",
                                    "IMAGE_API_KEY": "ark-key",
                                    "IMAGE_API_MODEL": "model-x",
                                },
                            }
                        ),
                    },
                    "edit prompt",
                    ["https://cdn.example.com/reference.png"],
                )

        request_ark_image.assert_called_once()
        request_payload = request_ark_image.call_args.args[2]
        self.assertEqual(request_payload["image"], "https://cdn.example.com/reference.png")
        self.assertEqual(request_payload["prompt"], "edit prompt")
        download_reference_image.assert_not_called()
        cover_key = build_generated_image_object_key("run-004b", 0, "edit prompt", 0)
        self.assertEqual(payload["cover_url"], f"https://cdn.example.com/{Path(cover_key).name}.png")
        self.assertEqual(payload["raw_results"][0]["provider"], "ark")
        self.assertEqual(
            payload["raw_results"][0]["reference_images"],
            [{"source_url": "https://cdn.example.com/reference.png"}],
        )
        self.assertEqual(uploader.url_calls, [("https://ark.example.com/edited.png", cover_key)])

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
                        "step": {},
                        "batch_id": "run-005",
                        "tenant_config": TenantRuntimeConfig(
                            payload={
                                "api_mode": "custom",
                                "api_ref": {
                                    "IMAGE_PROVIDER": "openai",
                                    "IMAGE_API_KEY": "image-key",
                                    "IMAGE_API_BASE_URL": "https://api.uniapi.io/v1",
                                    "IMAGE_API_MODEL": "gpt-image-2",
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
