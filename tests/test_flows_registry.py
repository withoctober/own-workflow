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
        self.assertEqual(rewrite_definition["name"], "爆款参考改写")
        self.assertEqual(rewrite_definition["description"], "粘贴一条参考笔记链接，系统提取结构后生成适合你品牌的二创内容。")
        self.assertEqual(rewrite_definition["step"], 4)
        self.assertEqual(rewrite_definition["scene"], "追热点 / 拆爆款")
        self.assertEqual(rewrite_definition["primary_action"], "粘贴链接改写")
        rewrite_schema = rewrite_definition["run_request_schema"]
        self.assertEqual(rewrite_schema["type"], "object")
        self.assertEqual(rewrite_schema["required"], ["source_url"])
        self.assertTrue(rewrite_schema["properties"]["source_url"]["required"])
        self.assertEqual(rewrite_schema["properties"]["source_url"]["default"], "")

        collect_definition = next(item for item in definitions if item["id"] == "content-collect")
        self.assertEqual(collect_definition["name"], "经营资料体检")
        self.assertEqual(collect_definition["description"], "先把品牌、行业、对标账号和热点素材整理好，让后续内容生成有依据。")
        self.assertEqual(collect_definition["step"], 1)
        self.assertEqual(collect_definition["scene"], "资料准备")
        collect_schema = collect_definition["run_request_schema"]
        self.assertEqual(collect_schema["required"], [])
        self.assertNotIn("source_url", collect_schema["properties"])

    def test_build_flow_definition_returns_content_collect_graph(self) -> None:
        flow = build_flow_definition(SimpleNamespace(flow_id="content-collect"))
        self.assertEqual(flow["entrypoint"], "collect-01-coordinator-check")
        self.assertIn("collect-08-topic-bank", flow["nodes"])


if __name__ == "__main__":
    unittest.main()
