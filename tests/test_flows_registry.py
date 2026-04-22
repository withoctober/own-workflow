from __future__ import annotations

import unittest
from types import SimpleNamespace

from workflow.flow.registry import build_flow_definition, list_flow_definitions


class FlowRegistryTest(unittest.TestCase):
    def test_lists_expected_flow_ids(self) -> None:
        ids = [item["id"] for item in list_flow_definitions()]
        self.assertEqual(
            ids,
            [
                "content-collect",
                "content-create-original",
                "content-create-rewrite",
                "daily-report",
            ],
        )

    def test_build_flow_definition_returns_content_collect_graph(self) -> None:
        flow = build_flow_definition(SimpleNamespace(flow_id="content-collect"))
        self.assertEqual(flow["entrypoint"], "collect-01-coordinator-check")
        self.assertIn("collect-08-topic-bank", flow["nodes"])


if __name__ == "__main__":
    unittest.main()
