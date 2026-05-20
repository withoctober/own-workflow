from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, patch

import app.routes as routes
from fastapi.testclient import TestClient

from app.main import create_app
from model import Artifact, StoreEntry, Tenant, TenantFlowSchedule, WorkflowRun
from workflow.runtime.tenant import TenantRuntimeConfig


class AppRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        routes._PROVIDER_MONITOR_CACHE.clear()

    @staticmethod
    def _create_test_app(tmpdir: str):
        root = Path(tmpdir)
        env_path = root / ".env"
        env_path.write_text(
            "DATABASE_URL=postgres://test:test@localhost:5432/testdb\nADMIN_TOKEN=test-admin-token\n",
            encoding="utf-8",
        )
        return create_app(root)

    @staticmethod
    def _tenant(
        tenant_id: str = "existing-tenant",
        tenant_name: str = "Existing Tenant",
        api_key: str = "existing-key",
        default_llm_model: str = "",
        api_mode: str = "system",
        api_ref: dict | None = None,
    ) -> Tenant:
        return Tenant(
            id="tenant-pk",
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            api_key=api_key,
            is_active=True,
            default_llm_model=default_llm_model,
            api_mode=api_mode,
            api_ref=api_ref or {},
            timeout_seconds=600,
            max_retries=2,
        )

    @staticmethod
    def _schedule() -> TenantFlowSchedule:
        return TenantFlowSchedule(
            id="schedule-pk",
            tenant_pk="tenant-pk",
            tenant_id="existing-tenant",
            flow_id="daily-report",
            cron_expr="*/15 * * * *",
            is_active=True,
            request_payload={"source_url": ""},
            batch_id_prefix="daily",
            next_run_at=datetime.fromisoformat("2026-04-23T07:00:00+08:00"),
            last_run_at=None,
            last_status="",
            last_error="",
            last_batch_id="",
            is_running=False,
            locked_at=None,
            created_at=None,
            updated_at=None,
        )

    @staticmethod
    def _store_entry(
        *,
        dataset_key: str = "products",
        record_key: str = "row-1",
        entry_type: str = "row",
        content_text: str = "",
        payload: dict | None = None,
    ) -> StoreEntry:
        return StoreEntry(
            id="entry-pk",
            tenant_id="existing-tenant",
            dataset_key=dataset_key,
            entry_type=entry_type,
            record_key=record_key,
            title="",
            batch_id="",
            sort_order=0,
            content_text=content_text,
            payload=payload or {"产品名称": "新品", "价格": "99"},
            schema_version=1,
            source_ref="",
            is_deleted=False,
            created_at=None,
            updated_at=None,
        )

    @staticmethod
    def _workflow_run(
        *,
        flow_id: str = "content-collect",
        batch_id: str = "20260423123015",
        trigger_mode: str = "manual",
        status: str = "completed",
        current_node: str = "",
    ) -> WorkflowRun:
        timestamp = datetime.fromisoformat("2026-04-23T12:30:15+08:00")
        return WorkflowRun(
            id="run-pk",
            tenant_id="existing-tenant",
            flow_id=flow_id,
            batch_id=batch_id,
            trigger_mode=trigger_mode,
            source_url="https://example.com/source",
            status=status,
            current_node=current_node,
            current_node_index=5 if current_node else 0,
            total_node_count=8,
            resume_count=1,
            completed_node_count=4,
            error_count=0,
            last_message="finished",
            last_error="",
            started_at=timestamp,
            finished_at=timestamp,
            created_at=timestamp,
            updated_at=timestamp,
        )

    @staticmethod
    def _artifact(
        *,
        artifact_id: str = "artifact-pk",
        flow_id: str = "content-create-original",
        batch_id: str = "20260424160000",
    ) -> Artifact:
        timestamp = datetime.fromisoformat("2026-04-24T16:00:00+08:00")
        return Artifact(
            id=artifact_id,
            tenant_id="existing-tenant",
            flow_id=flow_id,
            batch_id=batch_id,
            workflow_run_id=batch_id,
            artifact_type="content",
            title="新标题",
            content="这是正文",
            tags="#标签",
            cover_prompt="封面提示词",
            cover_url="https://cdn.example.com/cover.png",
            image_prompts=["配图提示词 1", "配图提示词 2"],
            image_urls=["https://cdn.example.com/1.png", "https://cdn.example.com/2.png"],
            source_url="https://example.com/source",
            payload={"copy": {"title": "新标题"}},
            created_at=timestamp,
            updated_at=timestamp,
        )

    @staticmethod
    def _wallet_entry(
        *,
        entry_id: str = "ledger-1",
        tenant_id: str = "existing-tenant",
        entry_type: str = "consume",
        amount: float = -12.5,
        title: str = "行业报告生成",
        channel: str = "文案生成",
        provider: str = "openai",
        provider_event_id: str = "evt-1",
        related_resource_type: str = "workflow_run",
        related_resource_id: str = "20260505093000",
        status: str = "completed",
        detail: str = "生成行业报告",
        metadata: dict | None = None,
    ):
        timestamp = datetime.fromisoformat("2026-05-05T09:30:00+08:00")
        return SimpleNamespace(
            id=entry_id,
            tenant_id=tenant_id,
            entry_type=entry_type,
            amount=amount,
            title=title,
            channel=channel,
            provider=provider,
            provider_event_id=provider_event_id,
            related_resource_type=related_resource_type,
            related_resource_id=related_resource_id,
            status=status,
            detail=detail,
            metadata=metadata or {"feature": "industry-report"},
            occurred_at=timestamp,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def test_get_health_returns_wrapped_success_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)

            response = client.get("/api/health")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {
                    "code": 0,
                    "message": "ok",
                    "data": {"status": "ok"},
                },
            )

    def test_cors_preflight_allows_any_origin(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)

            response = client.options(
                "/api/health",
                headers={
                    "Origin": "https://example.com",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "X-API-Key",
                },
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["access-control-allow-origin"], "*")
            self.assertIn("GET", response.headers["access-control-allow-methods"])
            self.assertIn("X-API-Key", response.headers["access-control-allow-headers"])

    def test_post_tenant_creates_tenant_with_generated_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            created_tenant = Tenant(
                id="tenant-pk",
                tenant_id="acme-brand",
                tenant_name="Acme Brand",
                api_key="acme-key",
                is_active=True,
                default_llm_model="",
                api_mode="custom",
                api_ref={"OPENAI_API_KEY": "tenant-openai-key"},
                timeout_seconds=600,
                max_retries=2,
            )

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.routes.get_tenant_by_api_key", return_value=None),
                patch("app.routes.generate_tenant_id", return_value="acme-brand") as generate_tenant_id,
                patch("app.routes.upsert_tenant", return_value=created_tenant) as upsert_tenant,
            ):
                response = client.post(
                    "/api/tenants",
                    headers={"X-Admin-Token": "test-admin-token"},
                    json={
                        "tenant_name": "Acme Brand",
                        "api_key": "acme-key",
                        "api_mode": "custom",
                        "api_ref": {
                            "OPENAI_API_KEY": "tenant-openai-key",
                            "OPENAI_BASE_URL": "https://tenant.example/v1",
                            "OPENAI_MODEL": "gpt-4.1-mini",
                            "TIKHUB_API_KEY": "tenant-tikhub-key",
                        },
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {
                    "code": 0,
                    "message": "ok",
                    "data": {
                        "tenant_id": "acme-brand",
                        "tenant_name": "Acme Brand",
                        "api_key": "acme-key",
                        "is_active": True,
                        "default_llm_model": "",
                        "api_mode": "custom",
                        "api_ref": {"OPENAI_API_KEY": "tenant-openai-key"},
                        "timeout_seconds": 600,
                        "max_retries": 2,
                    },
                },
            )
            generate_tenant_id.assert_called_once()
            upsert_tenant.assert_called_once()

    def test_post_tenant_returns_wrapped_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)

            response = client.post(
                "/api/tenants",
                headers={"X-Admin-Token": "test-admin-token"},
                json={},
            )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["code"], 422)
            self.assertEqual(body["message"], "validation error")
            self.assertIsInstance(body["data"], list)
            self.assertGreaterEqual(len(body["data"]), 1)

    def test_post_tenant_rejects_incomplete_api_ref_for_custom_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)

            response = client.post(
                "/api/tenants",
                headers={"X-Admin-Token": "test-admin-token"},
                json={
                    "tenant_name": "Acme Brand",
                    "api_key": "acme-key",
                    "api_mode": "custom",
                    "api_ref": {"OPENAI_API_KEY": "tenant-openai-key"},
                },
            )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["code"], 422)
            self.assertEqual(body["message"], "validation error")
            self.assertTrue(any("api_mode=custom" in str(item) for item in body["data"]))

    def test_get_tenants_requires_admin_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)

            response = client.get("/api/tenants")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {
                    "code": 401,
                    "message": "缺少 X-Admin-Token",
                    "data": "",
                },
            )

    def test_get_tenants_returns_tenant_list_for_admin(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.routes.list_tenants", return_value=[existing_tenant]),
            ):
                response = client.get("/api/tenants", headers={"X-Admin-Token": "test-admin-token"})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {
                    "code": 0,
                    "message": "ok",
                    "data": {
                        "tenants": [
                            {
                                "tenant_id": "existing-tenant",
                                "tenant_name": "Existing Tenant",
                                "is_active": True,
                                "default_llm_model": "",
                                "api_mode": "system",
                                "timeout_seconds": 600,
                                "max_retries": 2,
                            }
                        ]
                    },
                },
            )

    def test_get_tenant_tables_returns_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
            ):
                response = client.get("/api/tables", headers={"X-API-Key": "existing-key"})

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["code"], 0)
            self.assertTrue(any(item["dataset_key"] == "products" for item in body["data"]["tables"]))
            self.assertTrue(any(item["dataset_key"] == "industry_report" for item in body["data"]["tables"]))
            benchmark_table = next(item for item in body["data"]["tables"] if item["dataset_key"] == "benchmark_accounts")
            self.assertIn("粉丝数", benchmark_table["fields"])
            self.assertIn("账号定位", benchmark_table["fields"])
            hotspot_table = next(item for item in body["data"]["tables"] if item["dataset_key"] == "daily_hotspots")
            self.assertIn("热点ID", hotspot_table["fields"])
            report_table = next(item for item in body["data"]["tables"] if item["dataset_key"] == "industry_report")
            self.assertEqual(report_table["dataset_name"], "行业报告")
            self.assertEqual(report_table["fields"], ["文档"])

    def test_protected_endpoint_rejects_missing_api_key_before_database_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = create_app(Path(tmpdir))
            client = TestClient(app)

            response = client.get("/api/tables")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {
                    "code": 401,
                    "message": "缺少 X-API-Key",
                    "data": "",
                },
            )

    def test_api_key_authentication_uses_short_lived_app_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant) as get_tenant_by_api_key,
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes.list_store_entries", return_value=[self._store_entry()]),
            ):
                first = client.get("/api/tables/products", headers={"X-API-Key": "existing-key"})
                second = client.get("/api/tables/products", headers={"X-API-Key": "existing-key"})

            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(first.json()["code"], 0)
            self.assertEqual(second.json()["code"], 0)
            get_tenant_by_api_key.assert_called_once()

    def test_protected_endpoint_rejects_mismatched_body_tenant_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)

            with patch(
                "app.dependencies.get_tenant_by_api_key",
                return_value=self._tenant(tenant_id="tenant-a", api_key="tenant-a-key"),
            ):
                response = client.post(
                    "/api/flows/content-collect/runs",
                    headers={"X-API-Key": "tenant-a-key"},
                    json={"tenant_id": "tenant-b"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {
                    "code": 403,
                    "message": "X-API-Key 与 tenant_id 不匹配",
                    "data": "",
                },
            )

    def test_path_with_tenant_id_is_not_registered(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)

            with patch(
                "app.dependencies.get_tenant_by_api_key",
                return_value=self._tenant(tenant_id="tenant-a", api_key="tenant-a-key"),
            ):
                response = client.get(
                    "/api/flows/content-collect/runs/tenant-a/20260423120000",
                    headers={"X-API-Key": "tenant-a-key"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["code"], 404)

    def test_get_tenant_table_rows_returns_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes.list_store_entries", return_value=[self._store_entry()]),
            ):
                response = client.get("/api/tables/products", headers={"X-API-Key": "existing-key"})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["code"], 0)
            self.assertEqual(response.json()["data"]["dataset_key"], "products")
            self.assertEqual(response.json()["data"]["rows"][0]["record_id"], "row-1")

    def test_get_tenant_table_rows_passes_pagination_to_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes.list_store_entries", return_value=[self._store_entry()]) as list_store_entries,
            ):
                response = client.get(
                    "/api/tables/products?limit=12&offset=3&order=desc",
                    headers={"X-API-Key": "existing-key"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["code"], 0)
            list_store_entries.assert_called_once_with(
                ANY,
                tenant_id="existing-tenant",
                dataset_key="products",
                entry_type="row",
                limit=12,
                offset=3,
                order="desc",
                summary_mode="full",
            )

    def test_get_tenant_table_rows_uses_summary_mode_for_products_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes.list_store_entries", return_value=[self._store_entry()]) as list_store_entries,
            ):
                response = client.get(
                    "/api/tables/products?summary=true",
                    headers={"X-API-Key": "existing-key"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["code"], 0)
            list_store_entries.assert_called_once_with(
                ANY,
                tenant_id="existing-tenant",
                dataset_key="products",
                entry_type="row",
                limit=None,
                offset=0,
                order="asc",
                summary_mode="product_card",
            )

    def test_get_tenant_table_row_returns_full_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes.get_store_entry", return_value=self._store_entry(record_key="row-9")) as get_store_entry,
            ):
                response = client.get("/api/tables/products/row-9", headers={"X-API-Key": "existing-key"})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["code"], 0)
            self.assertEqual(response.json()["data"]["row"]["record_id"], "row-9")
            get_store_entry.assert_called_once_with(
                ANY,
                tenant_id="existing-tenant",
                dataset_key="products",
                entry_type="row",
                record_key="row-9",
            )

    def test_get_tenant_table_rows_wraps_doc_dataset_as_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch(
                    "app.routes.list_store_entries",
                    return_value=[
                        self._store_entry(
                            dataset_key="industry_report",
                            record_key="__doc__",
                            entry_type="doc",
                            content_text="行业报告正文",
                        )
                    ],
                ),
            ):
                response = client.get("/api/tables/industry_report", headers={"X-API-Key": "existing-key"})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["code"], 0)
            data = response.json()["data"]
            self.assertEqual(data["dataset_key"], "industry_report")
            self.assertEqual(data["dataset_name"], "行业报告")
            self.assertEqual(data["fields"], ["文档"])
            self.assertEqual(data["rows"], [{"record_id": "__doc__", "文档": "行业报告正文"}])

    def test_post_tenant_table_row_creates_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes.insert_store_rows", return_value=[self._store_entry(record_key="row-new")]) as insert_store_rows,
            ):
                response = client.post(
                    "/api/tables/products",
                    headers={"X-API-Key": "existing-key"},
                    json={"payload": {"产品名称": "新品", "价格": "99"}},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["code"], 0)
            self.assertEqual(response.json()["data"]["row"]["record_id"], "row-new")
            insert_store_rows.assert_called_once()

    def test_put_tenant_table_row_updates_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch(
                    "app.routes.get_store_entry",
                    return_value=self._store_entry(record_key="row-1", payload={"legacy_field": "keep", "产品名称": "旧产品", "价格": "99"}),
                ),
                patch(
                    "app.routes.update_store_rows",
                    return_value=[self._store_entry(record_key="row-1", payload={"legacy_field": "keep", "产品名称": "更新后", "价格": "199"})],
                ) as update_store_rows,
            ):
                response = client.put(
                    "/api/tables/products/row-1",
                    headers={"X-API-Key": "existing-key"},
                    json={"payload": {"产品名称": "更新后", "价格": "199"}},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["code"], 0)
            self.assertEqual(response.json()["data"]["row"]["产品名称"], "更新后")
            update_store_rows.assert_called_once_with(
                ANY,
                tenant_id="existing-tenant",
                dataset_key="products",
                rows=[{"legacy_field": "keep", "产品名称": "更新后", "价格": "199", "record_id": "row-1"}],
            )

    def test_delete_tenant_table_row_deletes_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes.soft_delete_store_entry", return_value=True) as soft_delete_store_entry,
            ):
                response = client.delete(
                    "/api/tables/products/row-1",
                    headers={"X-API-Key": "existing-key"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json()["data"],
                {
                    "tenant_id": "existing-tenant",
                    "dataset_key": "products",
                    "record_id": "row-1",
                    "deleted": True,
                },
            )
            soft_delete_store_entry.assert_called_once()

    def test_get_tenant_table_rows_rejects_unknown_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
            ):
                response = client.get("/api/tables/unknown-dataset", headers={"X-API-Key": "existing-key"})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {
                    "code": 404,
                    "message": "unknown dataset: unknown-dataset",
                    "data": "",
                },
            )

    def test_post_run_flow_injects_runtime_config_before_workflow_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=self._tenant(tenant_id="default", api_key="default-key")),
                patch(
                    "app.routes.get_tenant_runtime_config",
                    return_value={
                        "tenant_id": "default",
                        "api_mode": "system",
                        "api_ref": {},
                        "default_llm_model": "",
                        "tables": {},
                        "docs": {},
                        "timeout_seconds": 600,
                        "max_retries": 2,
                    },
                ) as get_tenant_runtime_config,
                patch(
                    "app.routes.GraphRuntime.enqueue",
                    return_value={
                        "status": "running",
                        "batch_id": "20260423120000",
                        "current_node": "",
                        "current_node_index": 0,
                        "total_node_count": 8,
                        "completed_nodes": [],
                    },
                ) as runtime_enqueue,
            ):
                response = client.post(
                    "/api/flows/content-collect/runs",
                    headers={"X-API-Key": "default-key"},
                    json={
                        "tenant_id": "default",
                        "image_additional_instruction": "把上传头像放在右下角做挂件",
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {
                    "code": 0,
                    "message": "ok",
                    "data": {
                        "status": "running",
                        "tenant_id": "default",
                        "flow_id": "content-collect",
                        "batch_id": "20260423120000",
                        "run_path": "/api/flows/content-collect/runs/20260423120000",
                        "current_node": "",
                        "current_node_index": 0,
                        "total_node_count": 8,
                        "completed_node_count": 0,
                    },
                },
            )
            get_tenant_runtime_config.assert_called_once()
            run_request = runtime_enqueue.call_args.args[0]
            self.assertEqual(run_request.trigger_mode, "manual")
            self.assertEqual(run_request.image_additional_instruction, "把上传头像放在右下角做挂件")
            self.assertIsInstance(run_request.tenant_runtime_config, TenantRuntimeConfig)
            self.assertEqual(run_request.tenant_runtime_config.payload["tenant_id"], "default")
            self.assertIn("api_mode", run_request.tenant_runtime_config.payload)

    def test_post_run_flow_uses_authenticated_tenant_when_body_omits_tenant_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch(
                    "app.dependencies.get_tenant_by_api_key",
                    return_value=self._tenant(tenant_id="tenant-2", tenant_name="速创猫", api_key="tenant-2-key"),
                ),
                patch(
                    "app.routes.get_tenant_runtime_config",
                    return_value={"tenant_id": "tenant-2", "tables": {}, "docs": {}, "timeout_seconds": 600, "max_retries": 2},
                ) as get_tenant_runtime_config,
                patch(
                    "app.routes.GraphRuntime.enqueue",
                    return_value={
                        "status": "running",
                        "batch_id": "20260423123000",
                        "current_node": "",
                        "current_node_index": 0,
                        "total_node_count": 8,
                        "completed_nodes": [],
                    },
                ) as runtime_enqueue,
            ):
                response = client.post(
                    "/api/flows/content-collect/runs",
                    headers={"X-API-Key": "tenant-2-key"},
                    json={},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {
                    "code": 0,
                    "message": "ok",
                    "data": {
                        "status": "running",
                        "tenant_id": "tenant-2",
                        "flow_id": "content-collect",
                        "batch_id": "20260423123000",
                        "run_path": "/api/flows/content-collect/runs/20260423123000",
                        "current_node": "",
                        "current_node_index": 0,
                        "total_node_count": 8,
                        "completed_node_count": 0,
                    },
                },
            )
            get_tenant_runtime_config.assert_called_once_with(ANY, "tenant-2")
            run_request = runtime_enqueue.call_args.args[0]
            self.assertEqual(run_request.tenant_id, "tenant-2")
            self.assertEqual(run_request.trigger_mode, "manual")
            self.assertIsInstance(run_request.tenant_runtime_config, TenantRuntimeConfig)
            self.assertEqual(run_request.tenant_runtime_config.payload["tenant_id"], "tenant-2")

    def test_post_run_flow_rejects_invalid_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=None),
            ):
                response = client.post(
                    "/api/flows/content-collect/runs",
                    headers={"X-API-Key": "bad-key"},
                    json={},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {
                    "code": 401,
                    "message": "X-API-Key 无效",
                    "data": "",
                },
            )

    def test_get_authenticated_run_uses_authenticated_tenant(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            run_state = {
                "flow_id": "content-collect",
                "tenant_id": "tenant-2",
                "batch_id": "20260423123015",
                "trigger_mode": "cron",
                "status": "running",
            }

            with (
                patch(
                    "app.dependencies.get_tenant_by_api_key",
                    return_value=self._tenant(tenant_id="tenant-2", tenant_name="速创猫", api_key="tenant-2-key"),
                ),
                patch("app.routes.load_run_state", return_value=run_state) as load_run_state,
            ):
                response = client.get(
                    "/api/flows/content-collect/runs/20260423123015",
                    headers={"X-API-Key": "tenant-2-key"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {
                    "code": 0,
                    "message": "ok",
                    "data": run_state,
                },
            )
            load_run_state.assert_called_once()
            self.assertEqual(load_run_state.call_args.args[1:], ("content-collect", "tenant-2", "20260423123015"))

    def test_get_runs_returns_current_tenant_run_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()
            workflow_run = self._workflow_run()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes.list_workflow_runs", return_value=([workflow_run], 1)) as list_workflow_runs,
            ):
                response = client.get(
                    "/api/runs?flow_id=content-collect&status=completed&limit=10&offset=0",
                    headers={"X-API-Key": "existing-key"},
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["code"], 0)
            self.assertEqual(body["data"]["tenant_id"], "existing-tenant")
            self.assertEqual(body["data"]["total"], 1)
            self.assertEqual(len(body["data"]["runs"]), 1)
            self.assertEqual(body["data"]["runs"][0]["batch_id"], "20260423123015")
            self.assertEqual(body["data"]["runs"][0]["trigger_mode"], "manual")
            self.assertEqual(body["data"]["runs"][0]["run_path"], "/api/flows/content-collect/runs/20260423123015")
            self.assertEqual(body["data"]["runs"][0]["current_node_index"], 0)
            self.assertEqual(body["data"]["runs"][0]["total_node_count"], 8)
            list_workflow_runs.assert_called_once_with(
                "postgres://test:test@localhost:5432/testdb",
                tenant_id="existing-tenant",
                flow_id="content-collect",
                status="completed",
                limit=10,
                offset=0,
            )

    def test_get_account_ledger_returns_summary_breakdown_and_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()
            ledger_entry = self._wallet_entry()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes._ensure_wallet_seed_data"),
                patch("app.routes.hydrate_provider_usage_from_ledger"),
                patch("app.routes.sync_tenant_wallet_balance"),
                patch(
                    "app.routes.summarize_wallet_balance",
                    return_value={"balance": 168.9, "recharge_total": 200.0, "consume_total": 31.1},
                ) as summarize_wallet_balance,
                patch(
                    "app.routes.summarize_wallet_period",
                    return_value={"consume_total": 12.5, "recharge_total": 100.0},
                ) as summarize_wallet_period,
                patch(
                    "app.routes.summarize_wallet_breakdown",
                    return_value=[{"channel": "文案生成", "amount": 12.5, "entry_count": 1}],
                ) as summarize_wallet_breakdown,
                patch(
                    "app.routes.summarize_wallet_daily_usage",
                    return_value=[{"date": "2026-05-05", "amount": 12.5}],
                ) as summarize_wallet_daily_usage,
                patch("app.routes.list_wallet_ledger_entries", return_value=([ledger_entry], 1)) as list_wallet_ledger_entries,
            ):
                response = client.get(
                    "/api/account/ledger?date_from=2026-05-01&date_to=2026-05-05&entry_type=consume&limit=5&offset=0",
                    headers={"X-API-Key": "existing-key"},
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["code"], 0)
            self.assertEqual(body["data"]["tenant_id"], "existing-tenant")
            self.assertEqual(body["data"]["total"], 1)
            self.assertEqual(body["data"]["summary"]["consume_total"], 12.5)
            self.assertEqual(body["data"]["balance"]["balance"], 168.9)
            self.assertEqual(body["data"]["breakdown"][0]["channel"], "文案生成")
            self.assertEqual(body["data"]["trend"][0]["date"], "2026-05-05")
            self.assertEqual(body["data"]["entries"][0]["entry_id"], "ledger-1")
            self.assertEqual(body["data"]["entries"][0]["provider"], "openai")
            summarize_wallet_balance.assert_called_once_with("postgres://test:test@localhost:5432/testdb", tenant_id="existing-tenant")
            summarize_wallet_period.assert_called_once_with(
                "postgres://test:test@localhost:5432/testdb",
                tenant_id="existing-tenant",
                date_from="2026-05-01",
                date_to="2026-05-05",
            )
            summarize_wallet_breakdown.assert_called_once_with(
                "postgres://test:test@localhost:5432/testdb",
                tenant_id="existing-tenant",
                date_from="2026-05-01",
                date_to="2026-05-05",
            )
            summarize_wallet_daily_usage.assert_called_once_with(
                "postgres://test:test@localhost:5432/testdb",
                tenant_id="existing-tenant",
                date_from="2026-05-01",
                date_to="2026-05-05",
            )
            list_wallet_ledger_entries.assert_called_once_with(
                "postgres://test:test@localhost:5432/testdb",
                tenant_id="existing-tenant",
                entry_type="consume",
                date_from="2026-05-01",
                date_to="2026-05-05",
                limit=5,
                offset=0,
            )

    def test_get_account_ledger_normalizes_all_entry_type_to_unfiltered_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes._ensure_wallet_seed_data"),
                patch("app.routes.hydrate_provider_usage_from_ledger"),
                patch("app.routes.sync_tenant_wallet_balance"),
                patch(
                    "app.routes.summarize_wallet_balance",
                    return_value={"balance": 656.92, "recharge_total": 700.0, "consume_total": 43.08},
                ),
                patch(
                    "app.routes.summarize_wallet_period",
                    return_value={"consume_total": 43.08, "recharge_total": 700.0},
                ),
                patch("app.routes.summarize_wallet_breakdown", return_value=[]),
                patch("app.routes.summarize_wallet_daily_usage", return_value=[]),
                patch("app.routes.list_wallet_ledger_entries", return_value=([], 0)) as list_wallet_ledger_entries,
            ):
                response = client.get(
                    "/api/account/ledger?entry_type=all&limit=10&offset=5",
                    headers={"X-API-Key": "existing-key"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["code"], 0)
            list_wallet_ledger_entries.assert_called_once_with(
                "postgres://test:test@localhost:5432/testdb",
                tenant_id="existing-tenant",
                entry_type="",
                date_from=None,
                date_to=None,
                limit=10,
                offset=5,
            )

    def test_get_account_ledger_passes_recharge_filter_to_wallet_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()
            ledger_entry = self._wallet_entry(
                entry_id="ledger-recharge-1",
                entry_type="recharge",
                amount=200.0,
                title="鏀粯瀹濆厖鍊?",
                channel="鍏呭€艰褰?",
                provider="manual",
                provider_event_id="recharge-evt-1",
                detail="鍏呭€肩粨鏋滄垚鍔?",
            )

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes._ensure_wallet_seed_data"),
                patch("app.routes.hydrate_provider_usage_from_ledger"),
                patch("app.routes.sync_tenant_wallet_balance"),
                patch(
                    "app.routes.summarize_wallet_balance",
                    return_value={"balance": 656.92, "recharge_total": 700.0, "consume_total": 43.08},
                ),
                patch(
                    "app.routes.summarize_wallet_period",
                    return_value={"consume_total": 0.0, "recharge_total": 200.0},
                ),
                patch("app.routes.summarize_wallet_breakdown", return_value=[]),
                patch("app.routes.summarize_wallet_daily_usage", return_value=[]),
                patch("app.routes.list_wallet_ledger_entries", return_value=([ledger_entry], 1)) as list_wallet_ledger_entries,
            ):
                response = client.get(
                    "/api/account/ledger?entry_type=recharge&limit=10&offset=0",
                    headers={"X-API-Key": "existing-key"},
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["code"], 0)
            self.assertEqual(body["data"]["entries"][0]["entry_type"], "recharge")
            self.assertEqual(body["data"]["entries"][0]["amount"], 200.0)
            list_wallet_ledger_entries.assert_called_once_with(
                "postgres://test:test@localhost:5432/testdb",
                tenant_id="existing-tenant",
                entry_type="recharge",
                date_from=None,
                date_to=None,
                limit=10,
                offset=0,
            )

    def test_get_account_balance_returns_cached_balance_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes._ensure_wallet_seed_data") as ensure_wallet_seed_data,
                patch(
                    "app.routes.summarize_wallet_balance",
                    return_value={"balance": 656.92, "recharge_total": 700.0, "consume_total": 43.08},
                ) as summarize_wallet_balance,
            ):
                response = client.get("/api/account/balance", headers={"X-API-Key": "existing-key"})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {
                    "code": 0,
                    "message": "ok",
                    "data": {
                        "tenant_id": "existing-tenant",
                        "balance": 656.92,
                        "recharge_total": 700.0,
                        "consume_total": 43.08,
                      },
                  },
              )

    def test_get_account_provider_monitors_reads_current_env_and_returns_two_cards(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "DATABASE_URL=postgres://test:test@localhost:5432/testdb",
                        "OPENAI_BASE_URL=https://right.codes/gemini/v1",
                        "OPENAI_MODEL=gemini-3.1-pro-preview",
                        "OPENAI_API_KEY=test-rightcode-key",
                        "OPENAI_IMAGE_BASE_URL=https://www.right.codes/draw/v1",
                        "OPENAI_IMAGE_MODEL=gpt-image-2",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            app = create_app(root)
            client = TestClient(app)
            existing_tenant = self._tenant()

            def fake_remote(url: str, *, headers=None, timeout=8.0):
                if "billing/usage" in url:
                    return None
                if "tikhub/user/get_user_info" in url:
                    return {"user_data": {"balance": "88.5", "free_credit": 12}}
                return None

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch(
                    "app.routes.get_tenant_runtime_config",
                    return_value={
                        "tenant_id": "existing-tenant",
                        "api_ref": {
                            "OPENAI_API_KEY": "tenant-rightcode-key",
                            "OPENAI_BASE_URL": "https://www.right.codes/gemini/v1",
                            "TIKHUB_API_KEY": "tenant-tikhub-key",
                        },
                    },
                ),
                patch("app.routes._ensure_wallet_seed_data") as ensure_wallet_seed_data,
                patch("app.routes.hydrate_provider_usage_from_ledger"),
                patch("app.routes.list_provider_usage_events", return_value=([], 0)),
                patch("app.routes.create_provider_usage_event"),
                patch("app.routes._fetch_rightcode_account_summary", return_value=({"balance": "66.6"}, "")),
                patch("app.routes._safe_json_request_json_verbose", side_effect=lambda *args, **kwargs: (fake_remote(args[0]), "")),
                patch(
                    "app.routes.summarize_provider_usage_windows",
                    return_value={
                        ("llm", "文案生成"): {"today": 1.2, "week": 2.3, "month": 3.4, "last_synced_at": datetime.fromisoformat("2026-05-08T10:00:00+08:00")},
                        ("openai", "图片生成"): {"today": 9.9, "week": 10.1, "month": 11.2, "last_synced_at": datetime.fromisoformat("2026-05-08T10:00:00+08:00")},
                        ("tikhub", "数据采集"): {"today": 0.4, "week": 0.5, "month": 0.6, "last_synced_at": datetime.fromisoformat("2026-05-08T10:00:00+08:00")},
                        ("content-generation", "额度监控"): {"today": 0.0, "week": 0.0, "month": 0.0, "last_synced_at": datetime.fromisoformat("2026-05-08T10:00:00+08:00")},
                        ("tikhub", "额度监控"): {"today": 0.0, "week": 0.0, "month": 0.0, "last_synced_at": datetime.fromisoformat("2026-05-08T10:00:00+08:00")},
                    },
                ),
            ):
                response = client.get("/api/account/provider-monitors", headers={"X-API-Key": "existing-key"})

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["code"], 0)
            self.assertEqual(body["data"]["tenant_id"], "existing-tenant")
            providers = body["data"]["providers"]
            self.assertEqual(len(providers), 2)
            self.assertEqual([item["provider_key"] for item in providers], ["content-generation", "tikhub"])
            self.assertEqual(providers[0]["provider_name"], "图文生成")
            self.assertEqual(providers[0]["status"], "healthy")
            self.assertEqual(providers[0]["balance"], 66.6)
            self.assertEqual(providers[0]["today_usage"], 11.1)
            self.assertEqual(providers[1]["balance"], 88.5)
            ensure_wallet_seed_data.assert_called_once_with("postgres://test:test@localhost:5432/testdb", "existing-tenant")

    def test_get_account_provider_monitors_marks_content_generation_unconfigured_without_tenant_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch(
                    "app.routes.get_tenant_runtime_config",
                    return_value={
                        "tenant_id": "existing-tenant",
                        "api_ref": {"TIKHUB_API_KEY": "tenant-tikhub-key"},
                    },
                ),
                patch("app.routes._ensure_wallet_seed_data"),
                patch("app.routes.hydrate_provider_usage_from_ledger"),
                patch("app.routes.list_provider_usage_events", return_value=([], 0)),
                patch("app.routes.create_provider_usage_event"),
                patch(
                    "app.routes.summarize_provider_usage_windows",
                    return_value={
                        ("llm", "文案生成"): {"today": 0.0, "week": 0.0, "month": 0.0, "last_synced_at": None},
                        ("openai", "图片生成"): {"today": 0.0, "week": 0.0, "month": 0.0, "last_synced_at": None},
                        ("tikhub", "数据采集"): {"today": 0.0, "week": 0.0, "month": 0.0, "last_synced_at": None},
                        ("content-generation", "额度监控"): {"today": 0.0, "week": 0.0, "month": 0.0, "last_synced_at": None},
                        ("tikhub", "额度监控"): {"today": 0.0, "week": 0.0, "month": 0.0, "last_synced_at": None},
                    },
                ),
            ):
                response = client.get("/api/account/provider-monitors", headers={"X-API-Key": "existing-key"})

            self.assertEqual(response.status_code, 200)
            body = response.json()
            providers = body["data"]["providers"]
            self.assertEqual(providers[0]["provider_key"], "content-generation")
            self.assertEqual(providers[0]["status"], "warning")
            self.assertEqual(providers[0]["note"], "请先在当前空间填写图文生成 API Key")

    def test_get_account_provider_monitors_returns_stale_cache_when_refresh_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()
            payload = {
                "tenant_id": "existing-tenant",
                "updated_at": "2026-05-08T10:00:00+08:00",
                "providers": [
                    {
                        "provider_key": "llm",
                        "provider_name": "LLM",
                        "category": "copywriting",
                        "status": "healthy",
                        "balance": 12.3,
                        "today_usage": 1.0,
                        "week_usage": 2.0,
                        "month_usage": 3.0,
                        "note": "",
                    }
                ],
            }

            with (
                patch.object(routes, "_PROVIDER_MONITOR_CACHE", {}),
                patch.object(routes, "PROVIDER_MONITOR_CACHE_TTL_SECONDS", 0.0),
                patch.object(routes, "PROVIDER_MONITOR_STALE_TTL_SECONDS", 300.0),
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes.get_tenant_runtime_config", return_value={}),
                patch("app.routes._ensure_wallet_seed_data"),
                patch(
                    "app.routes._build_provider_monitor_payload",
                    side_effect=[payload, RuntimeError("upstream timeout")],
                ) as build_payload,
            ):
                first = client.get("/api/account/provider-monitors", headers={"X-API-Key": "existing-key"})
                second = client.get("/api/account/provider-monitors", headers={"X-API-Key": "existing-key"})

            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(first.json()["data"], payload)
            self.assertEqual(second.json()["data"], payload)
            self.assertEqual(build_payload.call_count, 2)

    def test_ensure_wallet_seed_data_caches_successful_initialization(self) -> None:
        with (
            patch.object(routes, "_WALLET_SEEDED_TENANTS", set()),
            patch.object(routes, "_WALLET_SEED_GUARDS", {}),
            patch("app.routes.ensure_tenant_wallet") as ensure_tenant_wallet,
            patch("app.routes.hydrate_provider_usage_from_ledger", return_value=0) as hydrate_provider_usage_from_ledger,
            patch("app.routes.list_wallet_ledger_entries", return_value=([self._wallet_entry()], 1)) as list_wallet_ledger_entries,
        ):
            routes._ensure_wallet_seed_data("postgresql://example", "tenant-a")
            routes._ensure_wallet_seed_data("postgresql://example", "tenant-a")

        ensure_tenant_wallet.assert_called_once_with("postgresql://example", tenant_id="tenant-a")
        hydrate_provider_usage_from_ledger.assert_called_once_with("postgresql://example", tenant_id="tenant-a")
        list_wallet_ledger_entries.assert_called_once_with(
            "postgresql://example",
            tenant_id="tenant-a",
            limit=1,
            offset=0,
        )

    def test_ensure_wallet_seed_data_retries_after_failure(self) -> None:
        with (
            patch.object(routes, "_WALLET_SEEDED_TENANTS", set()),
            patch.object(routes, "_WALLET_SEED_GUARDS", {}),
            patch("app.routes.ensure_tenant_wallet") as ensure_tenant_wallet,
            patch("app.routes.hydrate_provider_usage_from_ledger", side_effect=[RuntimeError("boom"), 0]) as hydrate_provider_usage_from_ledger,
            patch("app.routes.list_wallet_ledger_entries", return_value=([self._wallet_entry()], 1)) as list_wallet_ledger_entries,
        ):
            with self.assertRaises(RuntimeError):
                routes._ensure_wallet_seed_data("postgresql://example", "tenant-a")

            routes._ensure_wallet_seed_data("postgresql://example", "tenant-a")

            self.assertIn(
                routes._wallet_seed_cache_key("postgresql://example", "tenant-a"),
                routes._WALLET_SEEDED_TENANTS,
            )
            self.assertEqual(routes._WALLET_SEED_GUARDS, {})

        self.assertEqual(ensure_tenant_wallet.call_count, 2)
        self.assertEqual(hydrate_provider_usage_from_ledger.call_count, 2)
        list_wallet_ledger_entries.assert_called_once_with(
            "postgresql://example",
            tenant_id="tenant-a",
            limit=1,
            offset=0,
        )

    def test_get_artifacts_returns_current_tenant_artifact_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()
            artifact = self._artifact()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes.list_artifacts", return_value=([artifact], 1)) as list_artifacts,
            ):
                response = client.get(
                    "/api/artifacts?flow_id=content-create-original&limit=10&offset=0",
                    headers={"X-API-Key": "existing-key"},
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["code"], 0)
            self.assertEqual(body["data"]["tenant_id"], "existing-tenant")
            self.assertEqual(body["data"]["total"], 1)
            self.assertEqual(body["data"]["items"][0]["artifact_id"], "artifact-pk")
            self.assertEqual(body["data"]["items"][0]["title"], "新标题")
            list_artifacts.assert_called_once_with(
                "postgres://test:test@localhost:5432/testdb",
                tenant_id="existing-tenant",
                flow_id="content-create-original",
                limit=10,
                offset=0,
            )

    def test_get_artifact_detail_returns_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()
            artifact = self._artifact()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes.get_artifact", return_value=artifact) as get_artifact,
            ):
                response = client.get(
                    "/api/artifacts/artifact-pk",
                    headers={"X-API-Key": "existing-key"},
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["code"], 0)
            self.assertEqual(body["data"]["artifact_id"], "artifact-pk")
            self.assertEqual(body["data"]["cover_url"], "https://cdn.example.com/cover.png")
            get_artifact.assert_called_once_with(
                "postgres://test:test@localhost:5432/testdb",
                tenant_id="existing-tenant",
                artifact_id="artifact-pk",
            )

    def test_delete_artifact_deletes_current_tenant_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes.delete_artifact", return_value=True) as delete_artifact,
            ):
                response = client.delete(
                    "/api/artifacts/artifact-pk",
                    headers={"X-API-Key": "existing-key"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json()["data"],
                {
                    "tenant_id": "existing-tenant",
                    "artifact_id": "artifact-pk",
                    "deleted": True,
                },
            )
            delete_artifact.assert_called_once_with(
                "postgres://test:test@localhost:5432/testdb",
                tenant_id="existing-tenant",
                artifact_id="artifact-pk",
            )

    def test_put_artifact_updates_current_tenant_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()
            updated_artifact = self._artifact()
            updated_artifact.title = "Updated Title"
            updated_artifact.content = "Updated Body"
            updated_artifact.tags = "#updated"

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes.update_artifact", return_value=updated_artifact) as update_artifact,
            ):
                response = client.put(
                    "/api/artifacts/artifact-pk",
                    headers={"X-API-Key": "existing-key"},
                    json={
                        "title": "Updated Title",
                        "content": "Updated Body",
                        "tags": "#updated",
                        "cover_prompt": "new cover prompt",
                        "cover_url": "https://cdn.example.com/new-cover.png",
                        "image_prompts": ["detail prompt"],
                        "image_urls": ["https://cdn.example.com/1.png"],
                        "payload": {"copy": {"title": "Updated Title"}},
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["code"], 0)
            self.assertEqual(response.json()["data"]["artifact_id"], "artifact-pk")
            self.assertEqual(response.json()["data"]["title"], "Updated Title")
            update_artifact.assert_called_once_with(
                "postgres://test:test@localhost:5432/testdb",
                tenant_id="existing-tenant",
                artifact_id="artifact-pk",
                title="Updated Title",
                content="Updated Body",
                tags="#updated",
                cover_prompt="new cover prompt",
                cover_url="https://cdn.example.com/new-cover.png",
                image_prompts=["detail prompt"],
                image_urls=["https://cdn.example.com/1.png"],
                payload={"copy": {"title": "Updated Title"}},
            )

    def test_regenerate_artifact_image_uses_edit_mode_with_reference_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()
            timestamp = datetime.fromisoformat("2026-04-24T16:00:00+08:00")
            artifact = Artifact(
                id="artifact-pk",
                tenant_id="existing-tenant",
                flow_id="content-create-original",
                batch_id="20260424160000",
                workflow_run_id="20260424160000",
                artifact_type="content",
                title="Title",
                content="Body",
                tags="#tag",
                cover_prompt="cover prompt",
                cover_url="https://cdn.example.com/cover.png",
                image_prompts=["detail prompt 1", "detail prompt 2"],
                image_urls=["https://cdn.example.com/1.png", "https://cdn.example.com/2.png"],
                source_url="https://example.com/source",
                payload={
                    "topic_context": {
                        "visual_reference": {
                            "avatar": {
                                "image_url": "data:image/png;base64,avatar",
                                "placement_instruction": "右下角做头像挂件",
                            }
                        },
                        "source_dataset": "products",
                        "product": {
                            "产品图片": [
                                {"url": "https://cdn.example.com/product-a.png"},
                                {"url": "https://cdn.example.com/product-b.png"},
                            ]
                        },
                    }
                },
                created_at=timestamp,
                updated_at=timestamp,
            )
            updated_artifact = Artifact(
                id="artifact-pk",
                tenant_id="existing-tenant",
                flow_id="content-create-original",
                batch_id="20260424160000",
                workflow_run_id="20260424160000",
                artifact_type="content",
                title="Title",
                content="Body",
                tags="#tag",
                cover_prompt="cover prompt",
                cover_url="https://cdn.example.com/cover.png",
                image_prompts=["detail prompt 1", "detail prompt 2"],
                image_urls=["https://cdn.example.com/new-1.png", "https://cdn.example.com/2.png"],
                source_url="https://example.com/source",
                payload={"last_regenerated_image_index": 1},
                created_at=timestamp,
                updated_at=timestamp,
            )

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes.get_artifact", return_value=artifact),
                patch(
                    "app.routes.get_tenant_runtime_config",
                    return_value={"tenant_id": "existing-tenant", "timeout_seconds": 600, "max_retries": 2},
                ),
                patch(
                    "app.routes.edit_image",
                    return_value={"cover_url": "https://cdn.example.com/new-1.png", "image_urls": [], "raw_results": [], "uploaded_results": []},
                ) as edit_image,
                patch("app.routes.update_artifact", return_value=updated_artifact) as update_artifact,
            ):
                response = client.post(
                    "/api/artifacts/artifact-pk/regenerate-image",
                    headers={"X-API-Key": "existing-key"},
                    json={"image_index": 1},
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["code"], 0)
            self.assertEqual(body["data"]["image_urls"][0], "https://cdn.example.com/new-1.png")
            self.assertEqual(edit_image.call_args.args[1], "detail prompt 1")
            self.assertEqual(
                edit_image.call_args.args[2],
                [
                    "https://cdn.example.com/1.png",
                    "data:image/png;base64,avatar",
                    "https://cdn.example.com/product-a.png",
                    "https://cdn.example.com/product-b.png",
                    "https://cdn.example.com/cover.png",
                    "https://cdn.example.com/2.png",
                ],
            )
            self.assertEqual(edit_image.call_args.kwargs["billing_context"]["feature_key"], "artifact-regenerate-image")
            self.assertEqual(edit_image.call_args.kwargs["billing_context"]["related_resource_id"], "artifact-pk")
            update_artifact.assert_called_once()

    def test_preview_artifact_image_edit_returns_generated_url_without_updating_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()
            artifact = self._artifact()
            artifact.payload = {
                "topic_context": {
                    "visual_reference": {
                        "avatar": {
                            "image_url": "data:image/png;base64,avatar",
                            "placement_instruction": "右下角做头像挂件",
                        }
                    },
                    "product": {
                        "images": [
                            {"url": "https://cdn.example.com/product-a.png"},
                        ]
                    },
                }
            }

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes.get_artifact", return_value=artifact),
                patch(
                    "app.routes.get_tenant_runtime_config",
                    return_value={"tenant_id": "existing-tenant", "timeout_seconds": 600, "max_retries": 2},
                ),
                patch(
                    "app.routes.edit_image",
                    return_value={"cover_url": "https://cdn.example.com/preview.png", "image_urls": [], "raw_results": [], "uploaded_results": []},
                ) as edit_image,
                patch("app.routes.update_artifact") as update_artifact,
            ):
                response = client.post(
                    "/api/artifacts/artifact-pk/preview-image-edit",
                    headers={"X-API-Key": "existing-key"},
                    json={"image_index": 1, "prompt": "preview prompt"},
                )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["code"], 0)
            self.assertEqual(set(body["data"]), {"generated_url", "image_index", "prompt"})
            self.assertEqual(body["data"]["image_index"], 1)
            self.assertEqual(body["data"]["prompt"], "preview prompt")
            self.assertEqual(body["data"]["generated_url"], "https://cdn.example.com/preview.png")
            self.assertEqual(edit_image.call_args.args[1], "preview prompt")
            self.assertEqual(
                edit_image.call_args.args[2],
                [
                    "https://cdn.example.com/1.png",
                    "data:image/png;base64,avatar",
                    "https://cdn.example.com/product-a.png",
                    "https://cdn.example.com/cover.png",
                    "https://cdn.example.com/2.png",
                ],
            )
            self.assertEqual(edit_image.call_args.kwargs["billing_context"]["feature_key"], "artifact-preview-image-edit")
            self.assertEqual(edit_image.call_args.kwargs["billing_context"]["related_resource_id"], "artifact-pk")
            update_artifact.assert_not_called()

    def test_post_resume_flow_reuses_existing_run_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=self._tenant(tenant_id="default", api_key="default-key")),
                patch(
                    "app.routes.get_tenant_runtime_config",
                    return_value={"tenant_id": "default", "tables": {}, "docs": {}, "timeout_seconds": 600, "max_retries": 2},
                ) as get_tenant_runtime_config,
                patch(
                    "app.routes.load_run_state",
                    return_value={
                        "source_url": "https://example.com/source",
                        "status": "failed",
                        "trigger_mode": "manual",
                        "image_additional_instruction": "把上传头像放在右下角做挂件",
                    },
                ) as load_run_state,
                patch(
                    "app.routes.GraphRuntime.enqueue",
                    return_value={
                        "status": "running",
                        "batch_id": "20260423070000",
                        "resume_count": 1,
                        "current_node": "",
                        "current_node_index": 0,
                        "total_node_count": 8,
                        "completed_nodes": [],
                    },
                ) as runtime_enqueue,
            ):
                response = client.post(
                    "/api/flows/content-collect/runs/20260423070000/resume",
                    headers={"X-API-Key": "default-key"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {
                    "code": 0,
                    "message": "ok",
                    "data": {
                        "status": "running",
                        "tenant_id": "default",
                        "flow_id": "content-collect",
                        "batch_id": "20260423070000",
                        "run_path": "/api/flows/content-collect/runs/20260423070000",
                        "resume_count": 1,
                        "current_node": "",
                        "current_node_index": 0,
                        "total_node_count": 8,
                        "completed_node_count": 0,
                    },
                },
            )
            get_tenant_runtime_config.assert_called_once()
            load_run_state.assert_called_once()
            run_request = runtime_enqueue.call_args.args[0]
            self.assertEqual(run_request.flow_id, "content-collect")
            self.assertEqual(run_request.tenant_id, "default")
            self.assertEqual(run_request.batch_id, "20260423070000")
            self.assertEqual(run_request.source_url, "https://example.com/source")
            self.assertEqual(run_request.trigger_mode, "manual")
            self.assertEqual(run_request.image_additional_instruction, "把上传头像放在右下角做挂件")
            self.assertIsInstance(run_request.tenant_runtime_config, TenantRuntimeConfig)
            self.assertTrue(run_request.resume)

    def test_post_authenticated_resume_flow_uses_authenticated_tenant(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch(
                    "app.dependencies.get_tenant_by_api_key",
                    return_value=self._tenant(tenant_id="tenant-2", tenant_name="速创猫", api_key="tenant-2-key"),
                ),
                patch(
                    "app.routes.get_tenant_runtime_config",
                    return_value={"tenant_id": "tenant-2", "tables": {}, "docs": {}, "timeout_seconds": 600, "max_retries": 2},
                ),
                patch(
                    "app.routes.load_run_state",
                    return_value={"source_url": "https://example.com/source", "status": "failed", "trigger_mode": "cron"},
                ) as load_run_state,
                patch(
                    "app.routes.GraphRuntime.enqueue",
                    return_value={
                        "status": "running",
                        "batch_id": "20260423123015",
                        "resume_count": 2,
                        "current_node": "",
                        "current_node_index": 0,
                        "total_node_count": 8,
                        "completed_nodes": [],
                    },
                ) as runtime_enqueue,
            ):
                response = client.post(
                    "/api/flows/content-collect/runs/20260423123015/resume",
                    headers={"X-API-Key": "tenant-2-key"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["code"], 0)
            self.assertEqual(response.json()["data"]["tenant_id"], "tenant-2")
            self.assertEqual(response.json()["data"]["batch_id"], "20260423123015")
            self.assertEqual(response.json()["data"]["current_node_index"], 0)
            self.assertEqual(response.json()["data"]["total_node_count"], 8)
            load_run_state.assert_called_once()
            self.assertEqual(load_run_state.call_args.args[1:], ("content-collect", "tenant-2", "20260423123015"))
            run_request = runtime_enqueue.call_args.args[0]
            self.assertEqual(run_request.tenant_id, "tenant-2")
            self.assertEqual(run_request.batch_id, "20260423123015")
            self.assertEqual(run_request.trigger_mode, "cron")
            self.assertTrue(run_request.resume)

    def test_trigger_tenant_schedule_reuses_runtime_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            schedule = self._schedule()
            schedule.request_payload = {"source_url": "https://example.com/post"}

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=self._tenant(api_key="existing-key")),
                patch("app.routes.get_tenant_by_id", return_value=self._tenant(api_key="existing-key")),
                patch("app.routes.get_tenant_flow_schedule", return_value=schedule),
                patch(
                    "app.routes.get_tenant_runtime_config",
                    return_value={"tenant_id": "existing-tenant", "tables": {}, "docs": {}, "timeout_seconds": 600, "max_retries": 2},
                ),
                patch(
                    "app.routes.GraphRuntime.run",
                    return_value={"status": "completed", "batch_id": "daily-20260423070000"},
                ) as runtime_run,
            ):
                response = client.post(
                    "/api/schedules/daily-report/trigger",
                    headers={"X-API-Key": "existing-key"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["code"], 0)
            run_request = runtime_run.call_args.args[0]
            self.assertEqual(run_request.trigger_mode, "manual")
            self.assertEqual(run_request.flow_id, "daily-report")
            self.assertEqual(run_request.tenant_id, "existing-tenant")
            self.assertEqual(run_request.source_url, "https://example.com/post")

    def test_put_tenant_schedule_upserts_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()
            schedule = self._schedule()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes.has_flow_definition", return_value=True),
                patch("app.routes.validate_cron_expression") as validate_cron_expression,
                patch("app.routes.compute_next_run_at", return_value=schedule.next_run_at),
                patch("app.routes.upsert_tenant_flow_schedule", return_value=schedule) as upsert_tenant_flow_schedule,
            ):
                response = client.put(
                    "/api/schedules/daily-report",
                    headers={"X-API-Key": "existing-key"},
                    json={
                        "cron": "*/15 * * * *",
                        "is_active": True,
                        "batch_id_prefix": "Daily Report",
                        "request_payload": {"source_url": ""},
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["code"], 0)
            self.assertEqual(response.json()["data"]["flow_id"], "daily-report")
            self.assertEqual(response.json()["data"]["cron"], "*/15 * * * *")
            validate_cron_expression.assert_called_once_with("*/15 * * * *")
            upsert_tenant_flow_schedule.assert_called_once()
            self.assertEqual(
                upsert_tenant_flow_schedule.call_args.kwargs["batch_id_prefix"],
                "daily-report",
            )
            self.assertEqual(
                upsert_tenant_flow_schedule.call_args.kwargs["request_payload"],
                {},
            )

    def test_put_tenant_schedule_keeps_non_empty_request_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()
            schedule = self._schedule()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes.has_flow_definition", return_value=True),
                patch("app.routes.validate_cron_expression"),
                patch("app.routes.compute_next_run_at", return_value=schedule.next_run_at),
                patch("app.routes.upsert_tenant_flow_schedule", return_value=schedule) as upsert_tenant_flow_schedule,
            ):
                response = client.put(
                    "/api/schedules/content-create-rewrite",
                    headers={"X-API-Key": "existing-key"},
                    json={
                        "cron": "0 9 * * *",
                        "is_active": True,
                        "batch_id_prefix": "rewrite",
                        "request_payload": {"source_url": "https://example.com/post"},
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["code"], 0)
            self.assertEqual(
                upsert_tenant_flow_schedule.call_args.kwargs["request_payload"],
                {"source_url": "https://example.com/post"},
            )

    def test_get_tenant_schedules_returns_schedule_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes.list_tenant_flow_schedules", return_value=[self._schedule()]),
            ):
                response = client.get("/api/schedules", headers={"X-API-Key": "existing-key"})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["code"], 0)
            self.assertEqual(len(response.json()["data"]["schedules"]), 1)
            self.assertEqual(response.json()["data"]["schedules"][0]["flow_id"], "daily-report")

    def test_get_tenant_schedule_returns_schedule_detail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes.get_tenant_flow_schedule", return_value=self._schedule()),
            ):
                response = client.get(
                    "/api/schedules/daily-report",
                    headers={"X-API-Key": "existing-key"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["code"], 0)
            self.assertEqual(response.json()["data"]["tenant_id"], "existing-tenant")
            self.assertEqual(response.json()["data"]["flow_id"], "daily-report")
            self.assertEqual(response.json()["data"]["cron"], "*/15 * * * *")

    def test_get_flows_uses_api_key_without_explicit_tenant_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)

            with (
                patch("app.dependencies.get_tenant_by_api_key", return_value=self._tenant()),
                patch(
                    "app.routes.GraphRuntime.list_flows",
                    return_value=[
                        {
                            "id": "content-collect",
                            "name": "内容采集",
                            "description": "采集行业关键词、行业报告、对标账号、热点和选题库。",
                            "run_request_schema": {
                                "type": "object",
                                "properties": {
                                    "tenant_id": {
                                        "type": "string",
                                        "description": "Optional explicit tenant ID. When omitted, server resolves tenant from X-API-Key.",
                                        "default": None,
                                        "required": False,
                                    },
                                    "batch_id": {
                                        "type": "string",
                                        "description": "Optional batch ID. If omitted, runtime generates one from current time.",
                                        "default": None,
                                        "required": False,
                                    },
                                },
                                "required": [],
                            },
                        }
                    ],
                ),
            ):
                response = client.get("/api/flows", headers={"X-API-Key": "existing-key"})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {
                    "code": 0,
                    "message": "ok",
                    "data": {
                        "flows": [
                            {
                                "id": "content-collect",
                                "name": "内容采集",
                                "description": "采集行业关键词、行业报告、对标账号、热点和选题库。",
                                "run_request_schema": {
                                    "type": "object",
                                    "properties": {
                                        "tenant_id": {
                                            "type": "string",
                                            "description": "Optional explicit tenant ID. When omitted, server resolves tenant from X-API-Key.",
                                            "default": None,
                                            "required": False,
                                        },
                                        "batch_id": {
                                            "type": "string",
                                            "description": "Optional batch ID. If omitted, runtime generates one from current time.",
                                            "default": None,
                                            "required": False,
                                        },
                                    },
                                    "required": [],
                                },
                            }
                        ]
                    },
                },
            )

if __name__ == "__main__":
    unittest.main()
