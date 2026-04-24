from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow.core.ai import ai_config
from workflow.runtime.tenant import TenantRuntimeConfig


class WorkflowAIConfigTest(unittest.TestCase):
    def test_ai_config_prefers_tenant_custom_api_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "OPENAI_API_KEY=system-key\nOPENAI_BASE_URL=https://system.example/v1\nOPENAI_MODEL=system-model\n",
                encoding="utf-8",
            )
            tenant_config = TenantRuntimeConfig(
                payload={
                    "api_mode": "custom",
                    "api_ref": {
                        "OPENAI_API_KEY": "tenant-key",
                        "OPENAI_BASE_URL": "https://tenant.example/v1",
                        "OPENAI_MODEL": "tenant-model",
                    },
                    "timeout_seconds": 45,
                    "max_retries": 3,
                }
            )

            config = ai_config(root, tenant_config=tenant_config)

        self.assertEqual(config.api_key, "tenant-key")
        self.assertEqual(config.base_url, "https://tenant.example/v1")
        self.assertEqual(config.model, "tenant-model")
        self.assertEqual(config.timeout_seconds, 45)
        self.assertEqual(config.max_retries, 3)

    def test_ai_config_falls_back_to_system_env_for_system_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "OPENAI_API_KEY=system-key\nOPENAI_BASE_URL=https://system.example/v1\nOPENAI_MODEL=system-model\n",
                encoding="utf-8",
            )
            tenant_config = TenantRuntimeConfig(payload={"api_mode": "system", "api_ref": {"OPENAI_API_KEY": "tenant-key"}})

            config = ai_config(root, tenant_config=tenant_config)

        self.assertEqual(config.api_key, "system-key")
        self.assertEqual(config.base_url, "https://system.example/v1")
        self.assertEqual(config.model, "system-model")

    def test_ai_config_custom_mode_does_not_fall_back_to_system_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "OPENAI_API_KEY=system-key\nOPENAI_BASE_URL=https://system.example/v1\nOPENAI_MODEL=system-model\n",
                encoding="utf-8",
            )
            tenant_config = TenantRuntimeConfig(
                payload={
                    "api_mode": "custom",
                    "api_ref": {},
                }
            )

            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
                ai_config(root, tenant_config=tenant_config)


if __name__ == "__main__":
    unittest.main()
