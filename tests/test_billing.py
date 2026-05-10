from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from workflow.billing import record_llm_usage, record_usage_event


class BillingTest(unittest.TestCase):
    @staticmethod
    def _write_env(root: Path, *, extra_lines: list[str] | None = None) -> None:
        lines = ["DATABASE_URL=postgresql://test:test@localhost:5432/testdb"]
        lines.extend(extra_lines or [])
        (root / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_record_usage_event_uses_request_rate_for_tikhub(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_env(root, extra_lines=["BILLING_TIKHUB_REQUEST_COST=0.12"])

            with (
                patch("workflow.billing.ensure_postgres_tables"),
                patch("workflow.billing.create_wallet_ledger_entry", return_value=SimpleNamespace(id="ledger-1")) as create_wallet_ledger_entry,
                patch("workflow.billing.create_provider_usage_event", return_value=SimpleNamespace(id="usage-1")) as create_provider_usage_event,
            ):
                result = record_usage_event(
                    root=root,
                    tenant_id="tenant-a",
                    provider="tikhub",
                    channel="数据采集",
                    title="对标笔记抓取",
                    detail="已记录对标笔记抓取",
                    feature_key="content-create-rewrite-fetch",
                    request_id="req-1",
                    request_count=2,
                    related_resource_type="workflow_run",
                    related_resource_id="20260505093000",
                    payload={"source_url": "https://example.com/post"},
                )

            self.assertIsNotNone(result)
            self.assertEqual(result["amount"], 0.24)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(create_wallet_ledger_entry.call_args.kwargs["amount"], -0.24)
            self.assertEqual(create_wallet_ledger_entry.call_args.kwargs["status"], "completed")
            self.assertEqual(create_provider_usage_event.call_args.kwargs["amount"], 0.24)
            self.assertEqual(create_provider_usage_event.call_args.kwargs["request_id"], "req-1")

    def test_record_llm_usage_marks_zero_amount_as_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_env(root)
            response = SimpleNamespace(
                usage_metadata={"input_tokens": 1200, "output_tokens": 300, "total_tokens": 1500},
                response_metadata={"model_name": "gpt-4.1-mini", "id": "resp-1", "token_usage": {"prompt_tokens": 1200, "completion_tokens": 300, "total_tokens": 1500}},
                content="hello",
            )

            with (
                patch("workflow.billing.ensure_postgres_tables"),
                patch("workflow.billing.create_wallet_ledger_entry", return_value=SimpleNamespace(id="ledger-2")) as create_wallet_ledger_entry,
                patch("workflow.billing.create_provider_usage_event", return_value=SimpleNamespace(id="usage-2")) as create_provider_usage_event,
            ):
                result = record_llm_usage(
                    root,
                    response=response,
                    tenant_id="tenant-a",
                    base_url="https://api.openai.com/v1",
                    title="日报生成",
                    channel="文案生成",
                    feature_key="daily-report-generate",
                    related_resource_type="workflow_run",
                    related_resource_id="20260505093000",
                    payload={"step_id": "daily-report-01-generate"},
                )

            self.assertIsNotNone(result)
            self.assertEqual(result["amount"], 0.0)
            self.assertEqual(result["status"], "recorded")
            self.assertEqual(create_wallet_ledger_entry.call_args.kwargs["status"], "recorded")
            self.assertEqual(create_wallet_ledger_entry.call_args.kwargs["amount"], 0.0)
            self.assertEqual(create_provider_usage_event.call_args.kwargs["tokens_in"], 1200)
            self.assertEqual(create_provider_usage_event.call_args.kwargs["tokens_out"], 300)
            self.assertEqual(create_provider_usage_event.call_args.kwargs["model_name"], "gpt-4.1-mini")


if __name__ == "__main__":
    unittest.main()
