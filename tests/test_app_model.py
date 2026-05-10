from __future__ import annotations

import json
import unittest
from types import ModuleType
from unittest.mock import MagicMock, patch

import model.db as db
from model import ensure_postgres_tables, generate_tenant_id, get_tenant_by_api_key, list_store_entries, slugify_tenant_name
from model.tenant import get_tenant_runtime_config
from model.wallet import _to_datetime, summarize_provider_usage_windows, summarize_wallet_balance


class AppModelTest(unittest.TestCase):
    def test_connect_postgres_reuses_pooled_connection(self) -> None:
        db._POSTGRES_POOLS.clear()

        class FakeConnection:
            def __init__(self) -> None:
                self.closed = False
                self.broken = False
                self.commit_calls = 0
                self.rollback_calls = 0

            def commit(self) -> None:
                self.commit_calls += 1

            def rollback(self) -> None:
                self.rollback_calls += 1

            def close(self) -> None:
                self.closed = True

        created_connections: list[FakeConnection] = []
        dict_row = object()

        fake_psycopg = ModuleType("psycopg")

        def fake_connect(database_url: str, *, row_factory):
            self.assertEqual(database_url, "postgresql://example")
            self.assertIs(row_factory, dict_row)
            connection = FakeConnection()
            created_connections.append(connection)
            return connection

        fake_psycopg.connect = fake_connect  # type: ignore[attr-defined]
        fake_psycopg_rows = ModuleType("psycopg.rows")
        fake_psycopg_rows.dict_row = dict_row  # type: ignore[attr-defined]

        with patch.dict("sys.modules", {"psycopg": fake_psycopg, "psycopg.rows": fake_psycopg_rows}):
            with db.connect_postgres("postgresql://example") as first:
                first_connection = first
            with db.connect_postgres("postgresql://example") as second:
                second_connection = second

        self.assertEqual(len(created_connections), 1)
        self.assertIs(first_connection, second_connection)
        self.assertEqual(created_connections[0].commit_calls, 2)
        self.assertEqual(created_connections[0].rollback_calls, 0)
        self.assertFalse(created_connections[0].closed)

    def test_wallet_to_datetime_expands_date_to_end_of_day(self) -> None:
        parsed = _to_datetime("2026-05-05", end_of_day=True)

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.isoformat(), "2026-05-05T23:59:59.999999")

    def test_wallet_to_datetime_keeps_explicit_timestamp_unchanged(self) -> None:
        parsed = _to_datetime("2026-05-05T09:30:00+08:00", end_of_day=True)

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.isoformat(), "2026-05-05T09:30:00+08:00")

    def test_summarize_wallet_balance_prefers_cached_wallet_row(self) -> None:
        wallet = type(
            "WalletStub",
            (),
            {
                "available_balance": 656.92,
                "total_recharged": 700.0,
                "total_consumed": 43.08,
            },
        )()

        with (
            patch("model.wallet.get_tenant_wallet", return_value=wallet) as get_tenant_wallet,
            patch("model.wallet.sync_tenant_wallet_balance") as sync_tenant_wallet_balance,
        ):
            summary = summarize_wallet_balance("postgresql://example", tenant_id="tenant-a")

        self.assertEqual(summary, {"balance": 656.92, "recharge_total": 700.0, "consume_total": 43.08})
        get_tenant_wallet.assert_called_once_with("postgresql://example", tenant_id="tenant-a")
        sync_tenant_wallet_balance.assert_not_called()

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
        self.assertEqual(json.loads(params[6]), {"OPENAI_API_KEY": "tenant-key"})

    def test_list_store_entries_supports_limit_offset_and_desc_order(self) -> None:
        mock_cursor = MagicMock()
        mock_connection = MagicMock()
        mock_connection.__enter__.return_value = mock_connection
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        with patch("model.store_entry.connect_postgres", return_value=mock_connection):
            rows = list_store_entries(
                "postgresql://example",
                tenant_id="tenant-a",
                dataset_key="topic_bank",
                entry_type="row",
                limit=20,
                offset=5,
                order="desc",
            )

        self.assertEqual(rows, [])
        sql, params = mock_cursor.execute.call_args.args
        self.assertIn("created_at desc", str(sql))
        self.assertIn("limit %s offset %s", str(sql))
        self.assertEqual(params, ["tenant-a", "topic_bank", "row", 20, 5])

    def test_list_store_entries_uses_summary_payload_for_product_cards(self) -> None:
        mock_cursor = MagicMock()
        mock_connection = MagicMock()
        mock_connection.__enter__.return_value = mock_connection
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        with patch("model.store_entry.connect_postgres", return_value=mock_connection):
            rows = list_store_entries(
                "postgresql://example",
                tenant_id="tenant-a",
                dataset_key="products",
                entry_type="row",
                limit=10,
                summary_mode="product_card",
            )

        self.assertEqual(rows, [])
        sql, params = mock_cursor.execute.call_args.args
        self.assertIn("payload - '产品图片'", str(sql))
        self.assertIn("产品图片数量", str(sql))
        self.assertIn("jsonb_typeof(payload -> '产品图片') = 'array'", str(sql))
        self.assertNotIn("(payload ->> '产品图片')::jsonb", str(sql))
        self.assertEqual(params, ["tenant-a", "products", "row", 10, 0])

    def test_summarize_provider_usage_windows_batches_requested_pairs(self) -> None:
        mock_cursor = MagicMock()
        mock_connection = MagicMock()
        mock_connection.__enter__.return_value = mock_connection
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {
                "provider": "openai",
                "channel": "图片生成",
                "today_amount": 1.2,
                "week_amount": 3.4,
                "month_amount": 5.6,
                "last_synced_at": _to_datetime("2026-05-08T10:00:00"),
            },
            {
                "provider": "tikhub",
                "channel": "数据采集",
                "today_amount": 0,
                "week_amount": 7.8,
                "month_amount": 9.1,
                "last_synced_at": None,
            },
        ]

        with patch("model.wallet.connect_postgres", return_value=mock_connection):
            summary = summarize_provider_usage_windows(
                "postgresql://example",
                tenant_id="tenant-a",
                provider_channels=[("openai", "图片生成"), ("tikhub", "数据采集"), ("openai", "图片生成")],
                today_from="2026-05-08",
                week_from="2026-05-02",
                month_from="2026-04-09",
            )

        self.assertEqual(summary[("openai", "图片生成")]["today"], 1.2)
        self.assertEqual(summary[("openai", "图片生成")]["week"], 3.4)
        self.assertEqual(summary[("openai", "图片生成")]["month"], 5.6)
        self.assertEqual(summary[("tikhub", "数据采集")]["week"], 7.8)
        sql, params = mock_cursor.execute.call_args.args
        self.assertIn("with requested(provider, channel) as", str(sql))
        self.assertEqual(params[0:4], ["openai", "图片生成", "tikhub", "数据采集"])
        self.assertEqual(params[-1], "tenant-a")

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

    def test_get_tenant_by_api_key_accepts_tenant_id_and_case_insensitive_lookup(self) -> None:
        mock_cursor = MagicMock()
        mock_connection = MagicMock()
        mock_connection.__enter__.return_value = mock_connection
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {
            "id": "tenant-pk",
            "tenant_id": "ownclaw",
            "tenant_name": "OwnClaw",
            "api_key": "OwnClaw",
            "is_active": True,
            "default_llm_model": "",
            "api_mode": "custom",
            "api_ref": {"OPENAI_API_KEY": "tenant-key"},
            "timeout_seconds": 600,
            "max_retries": 2,
        }

        with patch("model.tenant.connect_postgres", return_value=mock_connection):
            tenant = get_tenant_by_api_key("postgresql://example", "ownclaw")

        self.assertIsNotNone(tenant)
        assert tenant is not None
        self.assertEqual(tenant.tenant_id, "ownclaw")
        self.assertEqual(tenant.api_key, "OwnClaw")
        sql, params = mock_cursor.execute.call_args.args
        self.assertIn("lower(api_key) = lower(%s)", str(sql))
        self.assertIn("lower(tenant_id) = lower(%s)", str(sql))
        self.assertEqual(params, ("ownclaw", "ownclaw", "ownclaw", "ownclaw"))

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
