from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from workflow.integrations.image_generation import (
    ImageProviderConfig,
    OPENAI_IMAGE_USER_AGENT,
    DEFAULT_IMAGE_TIMEOUT_SECONDS,
    build_generated_image_object_key,
    build_image_payload,
    download_reference_image,
    edit_image,
    extract_generated_sources,
    generate_images,
    request_openai_image,
    request_openai_image_edit,
    resolve_image_config,
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
    def test_resolve_image_config_uses_system_base_url_and_tenant_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "OPENAI_IMAGE_BASE_URL=https://www.right.codes/draw/v1\nOPENAI_IMAGE_MODEL=gpt-image-2\n",
                encoding="utf-8",
            )

            config = resolve_image_config(
                {
                    "root": str(root),
                    "tenant_config": TenantRuntimeConfig(
                        payload={
                            "api_mode": "custom",
                            "api_ref": {"OPENAI_API_KEY": "tenant-openai-key"},
                        }
                    ),
                }
            )

        self.assertEqual(
            config,
            ImageProviderConfig("openai", "https://www.right.codes/draw/v1", "tenant-openai-key", "gpt-image-2"),
        )

    def test_resolve_image_config_prefers_tenant_image_base_url_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "OPENAI_IMAGE_BASE_URL=https://www.right.codes/draw/v1\nOPENAI_IMAGE_MODEL=gpt-image-2\n",
                encoding="utf-8",
            )

            config = resolve_image_config(
                {
                    "root": str(root),
                    "tenant_config": TenantRuntimeConfig(
                        payload={
                            "api_mode": "custom",
                            "api_ref": {
                                "OPENAI_API_KEY": "tenant-openai-key",
                                "OPENAI_IMAGE_BASE_URL": "https://right.codes/draw/v1",
                                "OPENAI_IMAGE_MODEL": "gpt-image-2",
                            },
                        }
                    ),
                }
            )

        self.assertEqual(config.base_url, "https://right.codes/draw/v1")
        self.assertEqual(config.model, "gpt-image-2")

    def test_generate_images_requires_image_base_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaisesRegex(StoreError, "OPENAI_IMAGE_BASE_URL"):
                generate_images(
                    {
                        "root": str(root),
                        "step": {},
                        "batch_id": "run-missing",
                        "tenant_config": TenantRuntimeConfig(
                            payload={"api_mode": "custom", "api_ref": {"OPENAI_API_KEY": "tenant-openai-key"}}
                        ),
                    },
                    ["prompt"],
                )

    def test_generate_images_requires_openai_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "OPENAI_IMAGE_BASE_URL=https://www.right.codes/draw/v1\nOPENAI_IMAGE_MODEL=gpt-image-2\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(StoreError, "OPENAI_API_KEY"):
                generate_images(
                    {
                        "root": str(root),
                        "step": {},
                        "batch_id": "run-missing",
                        "tenant_config": TenantRuntimeConfig(payload={"api_mode": "system", "api_ref": {}}),
                    },
                    ["prompt"],
                )

    def test_generate_images_uses_default_model_when_unset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "OPENAI_IMAGE_BASE_URL=https://www.right.codes/draw/v1\n",
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
                        "batch_id": "run-default-model",
                        "tenant_config": TenantRuntimeConfig(
                            payload={"api_mode": "custom", "api_ref": {"OPENAI_API_KEY": "tenant-openai-key"}}
                        ),
                    },
                    ["cover prompt"],
                )

        request_openai_image.assert_called_once()
        self.assertEqual(request_openai_image.call_args.args[2]["model"], "gpt-image-2")
        self.assertEqual(payload["raw_results"][0]["provider"], "openai")

    def test_generate_images_rejects_empty_prompts_before_remote_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "OPENAI_IMAGE_BASE_URL=https://www.right.codes/draw/v1\n",
                encoding="utf-8",
            )
            with (
                patch("workflow.integrations.image_generation.request_openai_image") as request_openai_image,
                self.assertRaisesRegex(StoreError, "image generation prompt at index 0 is empty"),
            ):
                generate_images(
                    {
                        "root": str(root),
                        "step": {},
                        "batch_id": "run-empty",
                        "tenant_config": TenantRuntimeConfig(
                            payload={"api_mode": "custom", "api_ref": {"OPENAI_API_KEY": "tenant-openai-key"}}
                        ),
                    },
                    ["", "   "],
                )

        request_openai_image.assert_not_called()

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
                        "step": {"image_size": "1024x1024"},
                        "batch_id": "run-003",
                        "tenant_config": TenantRuntimeConfig(
                            payload={
                                "api_mode": "custom",
                                "api_ref": {
                                    "OPENAI_API_KEY": "image-key",
                                    "OPENAI_IMAGE_BASE_URL": "https://www.right.codes/draw/v1",
                                    "OPENAI_IMAGE_MODEL": "gpt-image-2",
                                },
                            }
                        ),
                    },
                    ["cover prompt"],
                )

        request_openai_image.assert_called_once()
        self.assertEqual(request_openai_image.call_args.args[0], "image-key")
        self.assertEqual(request_openai_image.call_args.args[1], "https://www.right.codes/draw/v1")
        self.assertEqual(request_openai_image.call_args.args[2]["model"], "gpt-image-2")
        self.assertEqual(request_openai_image.call_args.args[2]["size"], "1024x1024")
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
                patch("workflow.integrations.image_generation.request_openai_image") as request_openai_image,
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
                                    "OPENAI_API_KEY": "image-key",
                                    "OPENAI_IMAGE_BASE_URL": "https://www.right.codes/draw/v1",
                                    "OPENAI_IMAGE_MODEL": "gpt-image-2",
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

    def test_build_image_payload_ignores_reference_images_for_openai(self) -> None:
        payload = build_image_payload(
            {"root": "E:/tmp", "step": {"image_size": "1536x1024"}},
            "edit prompt",
            ImageProviderConfig("openai", "https://www.right.codes/draw/v1", "tenant-openai-key", "gpt-image-2"),
            ["https://cdn.example.com/reference.png"],
        )

        self.assertEqual(
            payload,
            {
                "model": "gpt-image-2",
                "prompt": "edit prompt",
                "size": "1536x1024",
            },
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
                        "step": {},
                        "batch_id": "run-005",
                        "tenant_config": TenantRuntimeConfig(
                            payload={
                                "api_mode": "custom",
                                "api_ref": {
                                    "OPENAI_API_KEY": "image-key",
                                    "OPENAI_IMAGE_BASE_URL": "https://www.right.codes/draw/v1",
                                    "OPENAI_IMAGE_MODEL": "gpt-image-2",
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

    def test_edit_image_requires_reference_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "OPENAI_IMAGE_BASE_URL=https://www.right.codes/draw/v1\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(StoreError, "at least one reference image"):
                edit_image(
                    {
                        "root": str(root),
                        "step": {},
                        "batch_id": "run-005-empty",
                        "tenant_config": TenantRuntimeConfig(
                            payload={"api_mode": "custom", "api_ref": {"OPENAI_API_KEY": "tenant-openai-key"}}
                        ),
                    },
                    "edit prompt",
                    [],
                )

    def test_download_reference_image_supports_data_urls(self) -> None:
        payload = download_reference_image("data:image/png;base64,aGVsbG8=")

        self.assertEqual(payload["source_url"], "data:image/png;base64,aGVsbG8=")
        self.assertEqual(payload["content_type"], "image/png")
        self.assertEqual(payload["filename"], "reference-image.png")
        self.assertEqual(payload["data"], b"hello")

    def test_request_openai_image_sets_user_agent_header(self) -> None:
        captured: dict[str, object] = {}

        class _FakeImages:
            def generate(self, **payload):
                captured["payload"] = payload
                return SimpleNamespace(
                    model_dump=lambda mode="json": {
                        "created": 123,
                        "data": [{"url": "https://cdn.example.com/generated.png"}],
                    },
                    data=[SimpleNamespace(url="https://cdn.example.com/generated.png", b64_json=None, mime_type="image/png")],
                )

        class _FakeClient:
            def __init__(self, **kwargs):
                captured["client_kwargs"] = kwargs
                self.images = _FakeImages()

        with patch("openai.OpenAI", _FakeClient):
            response = request_openai_image(
                "image-key",
                "https://www.right.codes/draw/v1",
                {"model": "gpt-image-2", "prompt": "cover prompt"},
            )

        client_kwargs = captured["client_kwargs"]
        self.assertEqual(client_kwargs["api_key"], "image-key")
        self.assertEqual(client_kwargs["base_url"], "https://www.right.codes/draw/v1")
        self.assertEqual(client_kwargs["default_headers"], {"User-Agent": OPENAI_IMAGE_USER_AGENT})
        self.assertEqual(captured["payload"], {"model": "gpt-image-2", "prompt": "cover prompt"})
        self.assertEqual(response["data"], [{"url": "https://cdn.example.com/generated.png"}])

    def test_request_openai_image_edit_uses_rightcode_generations_endpoint(self) -> None:
        captured: dict[str, object] = {}

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(
                    {
                        "created": 123,
                        "data": [
                            {
                                "url": "https://cdn.example.com/edited.png",
                                "mime_type": "image/png",
                            }
                        ],
                    }
                ).encode("utf-8")

        def _fake_urlopen(request_obj, timeout=0):
            captured["url"] = request_obj.full_url
            captured["headers"] = dict(request_obj.header_items())
            captured["body"] = request_obj.data.decode("utf-8")
            captured["timeout"] = timeout
            return _FakeResponse()

        with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            response = request_openai_image_edit(
                "image-key",
                "https://www.right.codes/draw/v1",
                {"model": "gpt-image-2", "prompt": "edit prompt"},
                [
                    {
                        "source_url": "https://cdn.example.com/reference-1.png",
                        "filename": "reference-1.png",
                        "content_type": "image/png",
                        "data": b"first",
                    },
                    {
                        "source_url": "data:image/png;base64,aGVsbG8=",
                        "filename": "reference-2.png",
                        "content_type": "image/png",
                        "data": b"second",
                    },
                ],
            )

        self.assertEqual(captured["url"], "https://www.right.codes/draw/v1/images/generations")
        self.assertEqual(captured["timeout"], DEFAULT_IMAGE_TIMEOUT_SECONDS)
        self.assertEqual(captured["headers"]["Authorization"], "Bearer image-key")
        self.assertEqual(captured["headers"]["User-agent"], OPENAI_IMAGE_USER_AGENT)
        self.assertEqual(captured["headers"]["Content-type"], "application/json")
        self.assertEqual(
            json.loads(str(captured["body"])),
            {
                "model": "gpt-image-2",
                "prompt": "edit prompt",
                "image": [
                    "https://cdn.example.com/reference-1.png",
                    "data:image/png;base64,aGVsbG8=",
                ],
                "response_format": "url",
            },
        )
        self.assertEqual(response["data"], [{"url": "https://cdn.example.com/edited.png", "mime_type": "image/png"}])

    def test_extract_generated_sources_supports_raw_data_response(self) -> None:
        sources = extract_generated_sources(
            {
                "_raw_data": [
                    {"url": "https://cdn.example.com/edited.png", "mime_type": "image/png"},
                    {"b64_json": "aGVsbG8=", "mime_type": "image/png"},
                ]
            },
            "openai",
        )

        self.assertEqual(
            sources,
            [
                {"kind": "url", "source_url": "https://cdn.example.com/edited.png"},
                {"kind": "bytes", "data": b"hello", "mime_type": "image/png"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
