from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from workflow.flow.content_collect.nodes import PRODUCT_FIELDS, coordinator_check
from workflow.runtime.context import RuntimeContext
from workflow.runtime.tenant import TenantRuntimeConfig
from workflow.settings import WorkflowSettings


class _FakeStore:
    def __init__(self, tables: dict[str, list[dict[str, str]]]) -> None:
        self.tables = tables

    def read_table(self, name: str) -> list[dict[str, str]]:
        return list(self.tables.get(name, []))


class ContentCollectCoordinatorCheckTest(unittest.TestCase):
    def _runtime(self, root: Path) -> RuntimeContext:
        runtime = RuntimeContext(
            settings=WorkflowSettings.from_root(root),
            flow_id="content-collect",
            batch_id="20260430190000",
            tenant_id="tenant-a",
            tenant_runtime_config=TenantRuntimeConfig(payload={"tables": {}, "docs": {}}),
        )
        runtime.log_node_event = Mock()
        runtime.current_node_id = Mock(return_value="collect-01-coordinator-check")
        return runtime

    def test_partial_customer_profile_does_not_block_strategy_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._runtime(Path(tmpdir))
            runtime.store = Mock(
                return_value=_FakeStore(
                    {
                        "客户背景资料": [{"品牌名称": "示例品牌"}],
                        "产品库": [{field: f"value-{index}" for index, field in enumerate(PRODUCT_FIELDS[:8], start=1)}],
                        "对标账号库": [{"主页链接": "https://www.xiaohongshu.com/user/profile/example"}],
                    }
                )
            )

            result = coordinator_check(runtime)({})

        self.assertNotEqual(result.get("status"), "blocked")
        self.assertIn("资料校验通过", result.get("messages", []))

    def test_empty_customer_profile_still_blocks_strategy_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._runtime(Path(tmpdir))
            runtime.store = Mock(
                return_value=_FakeStore(
                    {
                        "客户背景资料": [{}],
                        "产品库": [{field: f"value-{index}" for index, field in enumerate(PRODUCT_FIELDS[:8], start=1)}],
                        "对标账号库": [{"主页链接": "https://www.xiaohongshu.com/user/profile/example"}],
                    }
                )
            )

            result = coordinator_check(runtime)({})

        self.assertEqual(result.get("status"), "blocked")
        self.assertIn("客户背景资料至少填写 1 个有效字段", result.get("errors", []))


if __name__ == "__main__":
    unittest.main()
