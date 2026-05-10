from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow.flow.content_create.utils import fetch_source_post_from_tikhub
from workflow.integrations.hotspots import fetch_and_normalize
from workflow.runtime.tenant import TenantRuntimeConfig
from workflow.store import StoreError


class TikhubCredentialPolicyTest(unittest.TestCase):
    def test_hotspots_requires_tenant_tikhub_key_without_env_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text("TIKHUB_API_KEY=env-only-key\n", encoding="utf-8")
            tenant_config = TenantRuntimeConfig(payload={"api_mode": "custom", "api_ref": {}})

            with self.assertRaisesRegex(RuntimeError, "missing_api_key:TIKHUB_API_KEY"):
                fetch_and_normalize(root, tenant_config=tenant_config)

    def test_fetch_source_post_requires_tenant_tikhub_key_without_env_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text("TIKHUB_API_KEY=env-only-key\n", encoding="utf-8")
            tenant_config = TenantRuntimeConfig(payload={"api_mode": "custom", "api_ref": {}})

            with self.assertRaisesRegex(StoreError, "缺少 TIKHUB_API_KEY"):
                fetch_source_post_from_tikhub(
                    root,
                    "https://www.xiaohongshu.com/explore/example-note-id",
                    tenant_config=tenant_config,
                )


if __name__ == "__main__":
    unittest.main()
