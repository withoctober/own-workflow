from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app
from app.model import Tenant
from workflow.runtime.tenant import TenantRuntimeConfig


class AppRoutesTest(unittest.TestCase):
    def test_get_health_returns_wrapped_success_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = create_app(Path(tmpdir))
            client = TestClient(app)

            response = client.get("/health")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {
                    "code": 0,
                    "message": "ok",
                    "data": {"status": "ok"},
                },
            )

    def test_post_tenant_creates_tenant_with_generated_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = create_app(Path(tmpdir))
            client = TestClient(app)
            created_tenant = Tenant(
                id="tenant-pk",
                tenant_id="acme-brand",
                tenant_name="Acme Brand",
                is_active=True,
                default_llm_model="",
                timeout_seconds=30,
                max_retries=2,
            )

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.routes.generate_tenant_id", return_value="acme-brand") as generate_tenant_id,
                patch("app.routes.upsert_tenant", return_value=created_tenant) as upsert_tenant,
            ):
                response = client.post(
                    "/tenants",
                    json={
                        "tenant_name": "Acme Brand",
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
                        "is_active": True,
                        "default_llm_model": "",
                        "timeout_seconds": 30,
                        "max_retries": 2,
                    },
                },
            )
            generate_tenant_id.assert_called_once()
            upsert_tenant.assert_called_once()

    def test_post_tenant_returns_wrapped_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = create_app(Path(tmpdir))
            client = TestClient(app)

            response = client.post(
                "/tenants",
                json={},
            )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["code"], 422)
            self.assertEqual(body["message"], "validation error")
            self.assertIsInstance(body["data"], list)
            self.assertGreaterEqual(len(body["data"]), 1)

    def test_put_tenant_feishu_returns_404_when_tenant_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = create_app(Path(tmpdir))
            client = TestClient(app)

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.routes.get_tenant_by_id", return_value=None),
                patch("app.routes.build_remote_feishu_config") as build_remote_feishu_config,
                patch("app.routes.upsert_tenant_feishu_config") as upsert_tenant_feishu_config,
                patch("app.routes.upsert_tenant") as upsert_tenant,
            ):
                response = client.put(
                    "/tenants/missing-tenant/feishu",
                    json={
                        "tenant_name": "Missing Tenant",
                        "app_id": "cli_xxx",
                        "app_secret": "secret",
                        "tenant_access_token": "",
                        "base_url": "https://example.com/base",
                        "industry_report_url": "https://example.com/report",
                        "marketing_plan_url": "https://example.com/plan",
                        "keyword_matrix_url": "https://example.com/keyword",
                        "default_llm_model": "gpt-5.4",
                        "timeout_seconds": 30,
                        "max_retries": 2,
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {
                    "code": 404,
                    "message": "tenant not found",
                    "data": "",
                },
            )
            build_remote_feishu_config.assert_not_called()
            upsert_tenant_feishu_config.assert_not_called()
            upsert_tenant.assert_not_called()

    def test_put_tenant_feishu_updates_existing_tenant(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = create_app(Path(tmpdir))
            client = TestClient(app)
            existing_tenant = Tenant(
                id="tenant-pk",
                tenant_id="existing-tenant",
                tenant_name="Existing Tenant",
                is_active=True,
                default_llm_model="gpt-5.4",
                timeout_seconds=30,
                max_retries=2,
            )

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.routes.get_tenant_by_id", side_effect=[existing_tenant, existing_tenant]),
                patch("app.routes.build_remote_feishu_config", return_value={"tables": {}, "docs": {}}),
                patch("app.routes.upsert_tenant", return_value=existing_tenant) as upsert_tenant,
                patch("app.routes.upsert_tenant_feishu_config"),
                patch(
                    "app.routes.get_tenant_feishu_config",
                    return_value=type(
                        "FeishuConfig",
                        (),
                        {
                            "app_id": "cli_xxx",
                            "app_secret": "secret",
                            "tenant_access_token": None,
                            "config": {"tables": {}, "docs": {}},
                        },
                    )(),
                ),
            ):
                response = client.put(
                    "/tenants/existing-tenant/feishu",
                    json={
                        "tenant_name": "Existing Tenant",
                        "app_id": "cli_xxx",
                        "app_secret": "secret",
                        "tenant_access_token": "",
                        "base_url": "https://example.com/base",
                        "industry_report_url": "https://example.com/report",
                        "marketing_plan_url": "https://example.com/plan",
                        "keyword_matrix_url": "https://example.com/keyword",
                        "default_llm_model": "gpt-5.4",
                        "timeout_seconds": 30,
                        "max_retries": 2,
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {
                    "code": 0,
                    "message": "ok",
                    "data": {
                        "tenant_id": "existing-tenant",
                        "tenant_name": "Existing Tenant",
                        "is_active": True,
                        "default_llm_model": "gpt-5.4",
                        "timeout_seconds": 30,
                        "max_retries": 2,
                        "app_id": "cli_xxx",
                        "app_secret": "secret",
                        "tenant_access_token": "",
                        "config": {"tables": {}, "docs": {}},
                    },
                },
            )
            upsert_tenant.assert_called_once()

    def test_put_tenant_feishu_returns_wrapped_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = create_app(Path(tmpdir))
            client = TestClient(app)

            response = client.put(
                "/tenants/existing-tenant/feishu",
                json={
                    "tenant_name": "Existing Tenant",
                    "app_id": "cli_xxx",
                },
            )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["code"], 422)
            self.assertEqual(body["message"], "validation error")
            self.assertIsInstance(body["data"], list)
            self.assertGreaterEqual(len(body["data"]), 1)

    def test_post_run_flow_injects_runtime_config_before_workflow_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = create_app(Path(tmpdir))
            client = TestClient(app)

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch(
                    "app.routes.get_feishu_runtime_config",
                    return_value={"tenant_id": "default", "tables": {}, "docs": {}, "timeout_seconds": 30, "max_retries": 2},
                ) as get_feishu_runtime_config,
                patch("app.routes.GraphRuntime.run", return_value={"status": "completed"}) as runtime_run,
            ):
                response = client.post(
                    "/flows/content-collect/runs",
                    json={
                        "tenant_id": "default",
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {
                    "code": 0,
                    "message": "ok",
                    "data": {"status": "completed"},
                },
            )
            get_feishu_runtime_config.assert_called_once()
            run_request = runtime_run.call_args.args[0]
            self.assertIsInstance(run_request.tenant_runtime_config, TenantRuntimeConfig)
            self.assertEqual(run_request.tenant_runtime_config.payload["tenant_id"], "default")


if __name__ == "__main__":
    unittest.main()
