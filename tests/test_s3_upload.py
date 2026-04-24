from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow.integrations.s3 import S3UploadConfig, S3Uploader, load_s3_upload_config
from workflow.store import StoreError


class _FakeResponse:
    def __init__(self, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self._body = body
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class S3UploadTest(unittest.TestCase):
    def test_load_s3_upload_config_reads_system_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "S3_ENDPOINT=https://system-s3.example.com",
                        "S3_REGION=system-region",
                        "S3_BUCKET=system-bucket",
                        "S3_ACCESS_KEY_ID=system-ak",
                        "S3_SECRET_ACCESS_KEY=system-sk",
                        "S3_KEY_PREFIX=system-prefix",
                        "S3_PUBLIC_BASE_URL=https://cdn.example.com/assets",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_s3_upload_config(root)

        self.assertEqual(config.endpoint, "https://system-s3.example.com")
        self.assertEqual(config.region, "system-region")
        self.assertEqual(config.bucket, "system-bucket")
        self.assertEqual(config.access_key_id, "system-ak")
        self.assertEqual(config.secret_access_key, "system-sk")
        self.assertEqual(config.key_prefix, "system-prefix")
        self.assertEqual(config.public_base_url, "https://cdn.example.com/assets")

    def test_load_s3_upload_config_requires_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "S3_ENDPOINT=https://system-s3.example.com\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(StoreError, "S3_REGION"):
                load_s3_upload_config(root)

    def test_upload_from_url_downloads_then_uploads_to_s3(self) -> None:
        uploader = S3Uploader(
            S3UploadConfig(
                endpoint="https://s3.example.com",
                region="cn-test-1",
                bucket="assets",
                access_key_id="ak",
                secret_access_key="sk",
                key_prefix="images",
                public_base_url="https://cdn.example.com/assets",
            )
        )
        requests: list[object] = []

        def fake_urlopen(req, timeout=0):
            requests.append(req)
            if len(requests) == 1:
                return _FakeResponse(b"png-bytes", {"Content-Type": "image/png"})
            return _FakeResponse(b"", {"ETag": '"etag-1"'})

        with patch("workflow.integrations.s3.request.urlopen", side_effect=fake_urlopen):
            uploaded = uploader.upload_from_url("https://origin.example.com/source", "generated-images/run-1/cover")

        self.assertEqual(uploaded.key, "images/generated-images/run-1/cover.png")
        self.assertEqual(uploaded.url, "https://cdn.example.com/assets/images/generated-images/run-1/cover.png")
        self.assertEqual(uploaded.content_type, "image/png")
        self.assertEqual(uploaded.size, len(b"png-bytes"))

        download_request = requests[0]
        upload_request = requests[1]
        self.assertEqual(download_request.full_url, "https://origin.example.com/source")
        self.assertEqual(upload_request.full_url, "https://assets.s3.example.com/images/generated-images/run-1/cover.png")
        self.assertEqual(upload_request.data, b"png-bytes")
        self.assertEqual(upload_request.get_method(), "PUT")
        self.assertTrue(upload_request.get_header("Authorization"))

    def test_upload_uses_virtual_host_style_url(self) -> None:
        uploader = S3Uploader(
            S3UploadConfig(
                endpoint="https://cos.ap-shanghai.myqcloud.com",
                region="ap-shanghai",
                bucket="workflow-1258170703",
                access_key_id="ak",
                secret_access_key="sk",
                key_prefix="uploads",
            )
        )
        requests: list[object] = []

        def fake_urlopen(req, timeout=0):
            requests.append(req)
            return _FakeResponse(b"", {"ETag": '"etag-2"'})

        with patch("workflow.integrations.s3.request.urlopen", side_effect=fake_urlopen):
            uploaded = uploader.upload_bytes(b"123", "generated-images/run-1/test.png", content_type="image/png")

        upload_request = requests[0]
        self.assertEqual(
            upload_request.full_url,
            "https://workflow-1258170703.cos.ap-shanghai.myqcloud.com/uploads/generated-images/run-1/test.png",
        )
        self.assertEqual(uploaded.key, "uploads/generated-images/run-1/test.png")
        self.assertEqual(
            uploaded.url,
            "https://workflow-1258170703.cos.ap-shanghai.myqcloud.com/uploads/generated-images/run-1/test.png",
        )


if __name__ == "__main__":
    unittest.main()
