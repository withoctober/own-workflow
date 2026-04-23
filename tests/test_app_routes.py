from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app
from app.model import Tenant, TenantFlowSchedule
from workflow.runtime.tenant import TenantRuntimeConfig


class AppRoutesTest(unittest.TestCase):
    @staticmethod
    def _create_test_app(tmpdir: str):
        root = Path(tmpdir)
        env_path = root / ".env"
        env_path.write_text("DATABASE_URL=postgres://test:test@localhost:5432/testdb\n", encoding="utf-8")
        return create_app(root)

    @staticmethod
    def _tenant(
        tenant_id: str = "existing-tenant",
        tenant_name: str = "Existing Tenant",
        api_key: str = "existing-key",
        default_llm_model: str = "",
    ) -> Tenant:
        return Tenant(
            id="tenant-pk",
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            api_key=api_key,
            is_active=True,
            default_llm_model=default_llm_model,
            timeout_seconds=30,
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

    def test_get_health_returns_wrapped_success_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
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
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            created_tenant = Tenant(
                id="tenant-pk",
                tenant_id="acme-brand",
                tenant_name="Acme Brand",
                api_key="acme-key",
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
                        "api_key": "acme-key",
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
                        "timeout_seconds": 30,
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
                "/tenants",
                json={},
            )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["code"], 422)
            self.assertEqual(body["message"], "validation error")
            self.assertIsInstance(body["data"], list)
            self.assertGreaterEqual(len(body["data"]), 1)

    def test_get_tenants_returns_tenant_list_without_api_key_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.routes.list_tenants", return_value=[existing_tenant]),
            ):
                response = client.get("/tenants")

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
                                "api_key": "existing-key",
                                "is_active": True,
                                "default_llm_model": "",
                                "timeout_seconds": 30,
                                "max_retries": 2,
                            }
                        ]
                    },
                },
            )

    def test_put_tenant_feishu_returns_404_when_tenant_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=self._tenant(tenant_id="missing-tenant", api_key="missing-key")),
                patch("app.routes.get_tenant_by_id", return_value=None),
                patch("app.routes.build_remote_feishu_config") as build_remote_feishu_config,
                patch("app.routes.upsert_tenant_feishu_config") as upsert_tenant_feishu_config,
                patch("app.routes.upsert_tenant") as upsert_tenant,
            ):
                response = client.put(
                    "/tenants/missing-tenant/feishu",
                    headers={"X-API-Key": "missing-key"},
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
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant(default_llm_model="gpt-5.4")

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
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
                    headers={"X-API-Key": "existing-key"},
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
                        "api_key": "existing-key",
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
            app = self._create_test_app(tmpdir)
            client = TestClient(app)

            with patch("app.dependencies.get_tenant_by_api_key", return_value=self._tenant()):
                response = client.put(
                    "/tenants/existing-tenant/feishu",
                    headers={"X-API-Key": "existing-key"},
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
            app = self._create_test_app(tmpdir)
            client = TestClient(app)

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=self._tenant(tenant_id="default", api_key="default-key")),
                patch(
                    "app.routes.get_feishu_runtime_config",
                    return_value={"tenant_id": "default", "tables": {}, "docs": {}, "timeout_seconds": 30, "max_retries": 2},
                ) as get_feishu_runtime_config,
                patch(
                    "app.routes.GraphRuntime.enqueue",
                    return_value={
                        "status": "running",
                        "batch_id": "20260423120000",
                    },
                ) as runtime_enqueue,
            ):
                response = client.post(
                    "/flows/content-collect/runs",
                    headers={"X-API-Key": "default-key"},
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
                    "data": {
                        "status": "running",
                        "tenant_id": "default",
                        "flow_id": "content-collect",
                        "batch_id": "20260423120000",
                        "run_path": "/flows/content-collect/runs/20260423120000",
                    },
                },
            )
            get_feishu_runtime_config.assert_called_once()
            run_request = runtime_enqueue.call_args.args[0]
            self.assertIsInstance(run_request.tenant_runtime_config, TenantRuntimeConfig)
            self.assertEqual(run_request.tenant_runtime_config.payload["tenant_id"], "default")

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
                    "/flows/content-collect/runs",
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

    def test_post_resume_flow_reuses_existing_run_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=self._tenant(tenant_id="default", api_key="default-key")),
                patch(
                    "app.routes.get_feishu_runtime_config",
                    return_value={"tenant_id": "default", "tables": {}, "docs": {}, "timeout_seconds": 30, "max_retries": 2},
                ) as get_feishu_runtime_config,
                patch(
                    "app.routes.load_run_state",
                    return_value={"source_url": "https://example.com/source", "status": "failed"},
                ) as load_run_state,
                patch(
                    "app.routes.GraphRuntime.enqueue",
                    return_value={"status": "running", "batch_id": "20260423070000", "resume_count": 1},
                ) as runtime_enqueue,
            ):
                response = client.post(
                    "/flows/content-collect/runs/default/20260423070000/resume",
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
                        "run_path": "/flows/content-collect/runs/20260423070000",
                        "resume_count": 1,
                    },
                },
            )
            get_feishu_runtime_config.assert_called_once()
            load_run_state.assert_called_once()
            run_request = runtime_enqueue.call_args.args[0]
            self.assertEqual(run_request.flow_id, "content-collect")
            self.assertEqual(run_request.tenant_id, "default")
            self.assertEqual(run_request.batch_id, "20260423070000")
            self.assertEqual(run_request.source_url, "https://example.com/source")
            self.assertIsInstance(run_request.tenant_runtime_config, TenantRuntimeConfig)
            self.assertTrue(run_request.resume)

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
                    "/tenant/schedules/daily-report",
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
                response = client.get("/tenant/schedules", headers={"X-API-Key": "existing-key"})

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
                    "/tenant/schedules/daily-report",
                    headers={"X-API-Key": "existing-key"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["code"], 0)
            self.assertEqual(response.json()["data"]["tenant_id"], "existing-tenant")
            self.assertEqual(response.json()["data"]["flow_id"], "daily-report")
            self.assertEqual(response.json()["data"]["cron"], "*/15 * * * *")

    def test_trigger_tenant_schedule_reuses_runtime_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)
            existing_tenant = self._tenant()
            schedule = self._schedule()
            schedule.request_payload = {"source_url": "https://example.com/post"}

            with (
                patch("app.routes.postgres_enabled", return_value=True),
                patch("app.routes.ensure_postgres_tables"),
                patch("app.dependencies.get_tenant_by_api_key", return_value=existing_tenant),
                patch("app.routes.get_tenant_by_id", return_value=existing_tenant),
                patch("app.routes.get_tenant_flow_schedule", return_value=schedule),
                patch(
                    "app.routes.get_feishu_runtime_config",
                    return_value={"tenant_id": "existing-tenant", "tables": {}, "docs": {}, "timeout_seconds": 30, "max_retries": 2},
                ),
                patch("app.routes.GraphRuntime.run", return_value={"status": "completed"}) as runtime_run,
            ):
                response = client.post(
                    "/tenant/schedules/daily-report/trigger",
                    headers={"X-API-Key": "existing-key"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["data"]["status"], "completed")
            run_request = runtime_run.call_args.args[0]
            self.assertEqual(run_request.flow_id, "daily-report")
            self.assertEqual(run_request.tenant_id, "existing-tenant")
            self.assertEqual(run_request.source_url, "https://example.com/post")

    def test_get_flows_uses_api_key_without_explicit_tenant_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)

            with (
                patch("app.dependencies.get_tenant_by_api_key", return_value=self._tenant()),
                patch("app.routes.GraphRuntime.list_flows", return_value=[{"id": "content-collect"}]),
            ):
                response = client.get("/flows", headers={"X-API-Key": "existing-key"})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {
                    "code": 0,
                    "message": "ok",
                    "data": {"flows": [{"id": "content-collect"}]},
                },
            )

    def test_rejects_mismatched_tenant_id_in_legacy_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._create_test_app(tmpdir)
            client = TestClient(app)

            with patch(
                "app.dependencies.get_tenant_by_api_key",
                return_value=self._tenant(tenant_id="existing-tenant", api_key="existing-key"),
            ):
                response = client.get(
                    "/tenants/other-tenant/schedules",
                    headers={"X-API-Key": "existing-key"},
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


if __name__ == "__main__":
    unittest.main()
