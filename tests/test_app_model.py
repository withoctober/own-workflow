from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from model import ensure_postgres_tables, generate_tenant_id, get_tenant_by_api_key, slugify_tenant_name
from model.tenant import get_tenant_runtime_config


class AppModelTest(unittest.TestCase):
    def test_ensure_postgres_tables_runs_legacy_column_migrations(self) -> None:
        mock_cursor = MagicMock()
        mock_connection = MagicMock()
        mock_connection.__enter__.return_value = mock_connection
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

        with patch("model.db.connect_postgres", return_value=mock_connection):
            ensure_postgres_tables("postgresql://example")

        executed_sql = "\n".join(str(call.args[0]) for call in mock_cursor.execute.call_args_list)
        self.assertIn("alter table tenants rename column tenant_key to tenant_id", executed_sql)
        self.assertIn("alter table tenants add column api_mode", executed_sql)
        self.assertIn("alter table tenants add column api_ref", executed_sql)
        self.assertIn("alter table tenants alter column timeout_seconds set default 600", executed_sql)
        self.assertIn("update tenants", executed_sql)
        self.assertIn("create table if not exists workflow_runs", executed_sql)
        self.assertIn("alter table workflow_runs add column trigger_mode", executed_sql)
        self.assertIn("create index if not exists ix_workflow_runs_tenant_updated", executed_sql)
        self.assertIn("create table if not exists artifacts", executed_sql)
        self.assertIn("create index if not exists ix_artifacts_tenant_updated", executed_sql)
        mock_connection.commit.assert_called_once()

    def test_slugify_tenant_name_normalizes_display_name(self) -> None:
        self.assertEqual(slugify_tenant_name(" Acme Brand "), "acme-brand")
        self.assertEqual(slugify_tenant_name("!!!"), "tenant")

    def test_generate_tenant_id_uses_increment_suffix_for_duplicates(self) -> None:
        with patch("model.tenant.list_tenant_ids", return_value=["acme-brand", "acme-brand-2"]):
            tenant_id = generate_tenant_id("postgresql://example", "Acme Brand")

        self.assertEqual(tenant_id, "acme-brand-3")

    def test_upsert_tenant_insert_statement_matches_parameters(self) -> None:
        mock_cursor = MagicMock()
        mock_connection = MagicMock()
        mock_connection.__enter__.return_value = mock_connection
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {
            "id": "tenant-pk",
            "tenant_id": "acme-brand",
            "tenant_name": "Acme Brand",
            "api_key": "acme-key",
            "is_active": True,
            "default_llm_model": "",
            "api_mode": "custom",
            "api_ref": {"OPENAI_API_KEY": "tenant-key"},
            "timeout_seconds": 600,
            "max_retries": 2,
        }

        with patch("model.tenant.connect_postgres", return_value=mock_connection):
            from model import upsert_tenant

            upsert_tenant(
                "postgresql://example",
                tenant_id="acme-brand",
                tenant_name="Acme Brand",
                api_key="acme-key",
                is_active=True,
                default_llm_model="",
                api_mode="custom",
                api_ref={"OPENAI_API_KEY": "tenant-key"},
                timeout_seconds=600,
                max_retries=2,
            )

        execute_args = mock_cursor.execute.call_args.args
        sql, params = execute_args
        self.assertEqual(str(sql).count("%s"), len(params))
        self.assertIn("api_key", str(sql))
        self.assertEqual(params[2], "acme-key")
        self.assertEqual(params[5], "custom")
        self.assertEqual(params[6], {"OPENAI_API_KEY": "tenant-key"})

    def test_get_tenant_by_api_key_returns_tenant(self) -> None:
        mock_cursor = MagicMock()
        mock_connection = MagicMock()
        mock_connection.__enter__.return_value = mock_connection
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {
            "id": "tenant-pk",
            "tenant_id": "acme-brand",
            "tenant_name": "Acme Brand",
            "api_key": "acme-key",
            "is_active": True,
            "default_llm_model": "",
            "api_mode": "custom",
            "api_ref": {"OPENAI_API_KEY": "tenant-key"},
            "timeout_seconds": 600,
            "max_retries": 2,
        }

        with patch("model.tenant.connect_postgres", return_value=mock_connection):
            tenant = get_tenant_by_api_key("postgresql://example", "acme-key")

        self.assertIsNotNone(tenant)
        assert tenant is not None
        self.assertEqual(tenant.tenant_id, "acme-brand")
        self.assertEqual(tenant.api_key, "acme-key")
        self.assertEqual(tenant.api_mode, "custom")
        self.assertEqual(tenant.api_ref, {"OPENAI_API_KEY": "tenant-key"})

    def test_get_tenant_runtime_config_keeps_api_ref_only_for_custom_mode(self) -> None:
        with patch(
            "model.tenant.get_tenant_by_id",
            return_value=type(
                "TenantStub",
                (),
                {
                    "tenant_id": "acme-brand",
                    "api_mode": "custom",
                    "api_ref": {"OPENAI_API_KEY": "tenant-key"},
                    "default_llm_model": "gpt-4.1",
                    "timeout_seconds": 45,
                    "max_retries": 3,
                },
            )(),
        ):
            payload = get_tenant_runtime_config("postgresql://example", "acme-brand")

        assert payload is not None
        self.assertEqual(payload["api_mode"], "custom")
        self.assertEqual(payload["api_ref"], {"OPENAI_API_KEY": "tenant-key"})
        self.assertEqual(payload["default_llm_model"], "gpt-4.1")


if __name__ == "__main__":
    unittest.main()
