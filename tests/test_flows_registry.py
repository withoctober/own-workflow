from __future__ import annotations

import unittest
from types import SimpleNamespace

from workflow.flow.registry import build_flow_definition, list_flow_definitions


class FlowRegistryTest(unittest.TestCase):
    def test_lists_expected_flow_ids(self) -> None:
        definitions = list_flow_definitions()
        ids = [item["id"] for item in definitions]
        self.assertEqual(
            ids,
            [
                "content-collect",
                "content-create-original",
                "content-create-rewrite",
                "daily-report",
            ],
        )
        rewrite_definition = next(item for item in definitions if item["id"] == "content-create-rewrite")
        rewrite_schema = rewrite_definition["run_request_schema"]
        self.assertEqual(rewrite_schema["type"], "object")
        self.assertEqual(rewrite_schema["required"], ["source_url"])
        self.assertTrue(rewrite_schema["properties"]["source_url"]["required"])
        self.assertEqual(rewrite_schema["properties"]["source_url"]["default"], "")

        collect_definition = next(item for item in definitions if item["id"] == "content-collect")
        collect_schema = collect_definition["run_request_schema"]
        self.assertEqual(collect_schema["required"], [])
        self.assertNotIn("source_url", collect_schema["properties"])

    def test_build_flow_definition_returns_content_collect_graph(self) -> None:
        flow = build_flow_definition(SimpleNamespace(flow_id="content-collect"))
        self.assertEqual(flow["entrypoint"], "collect-01-coordinator-check")
        self.assertIn("collect-08-topic-bank", flow["nodes"])


if __name__ == "__main__":
    unittest.main()
