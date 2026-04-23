from __future__ import annotations

import unittest

from workflow.runtime.tenant import TenantRuntimeConfig
from workflow.store.database import DatabaseStore
from workflow.store.base import StoreError


class DatabaseStoreTest(unittest.TestCase):
    def test_list_table_fields_returns_registry_fields(self) -> None:
        store = DatabaseStore(
            TenantRuntimeConfig(
                payload={
                    "tenant_id": "tenant-a",
                    "database_url": "postgresql://example",
                    "store_type": "database",
                }
            )
        )

        fields = store.list_table_fields("生成作品库")

        self.assertIn("标题", fields)
        self.assertIn("正文", fields)

    def test_benchmark_accounts_fields_align_previous_table(self) -> None:
        store = DatabaseStore(
            TenantRuntimeConfig(
                payload={
                    "tenant_id": "tenant-a",
                    "database_url": "postgresql://example",
                    "store_type": "database",
                }
            )
        )

        fields = store.list_table_fields("对标账号库")

        self.assertEqual(fields[0], "主页链接")
        self.assertIn("粉丝数", fields)
        self.assertIn("小红书号", fields)
        self.assertIn("点赞收藏数", fields)
        self.assertIn("账号定位", fields)

    def test_product_fields_include_competitor_positioning_and_optional_business_fields(self) -> None:
        store = DatabaseStore(
            TenantRuntimeConfig(
                payload={
                    "tenant_id": "tenant-a",
                    "database_url": "postgresql://example",
                    "store_type": "database",
                }
            )
        )

        fields = store.list_table_fields("产品库")

        self.assertIn("竞品定位", fields)
        self.assertIn("利润空间", fields)
        self.assertIn("不适合人群", fields)

    def test_daily_hotspots_fields_align_normalized_hotspot_rows(self) -> None:
        store = DatabaseStore(
            TenantRuntimeConfig(
                payload={
                    "tenant_id": "tenant-a",
                    "database_url": "postgresql://example",
                    "store_type": "database",
                }
            )
        )

        fields = store.list_table_fields("每日热点")

        self.assertIn("热榜标题", fields)
        self.assertIn("热点ID", fields)
        self.assertIn("图标链接", fields)
        self.assertIn("标题图片链接", fields)

    def test_analytics_fields_are_registered_for_daily_report_inputs(self) -> None:
        store = DatabaseStore(
            TenantRuntimeConfig(
                payload={
                    "tenant_id": "tenant-a",
                    "database_url": "postgresql://example",
                    "store_type": "database",
                }
            )
        )

        fields = store.list_table_fields("数据分析")

        self.assertIn("阅读量", fields)
        self.assertIn("互动率", fields)
        self.assertIn("分析结论", fields)

    def test_requires_database_runtime_config(self) -> None:
        with self.assertRaises(StoreError):
            DatabaseStore(TenantRuntimeConfig(payload={"tenant_id": "tenant-a", "store_type": "database"}))

    def test_unknown_dataset_raises_store_error(self) -> None:
        store = DatabaseStore(
            TenantRuntimeConfig(
                payload={
                    "tenant_id": "tenant-a",
                    "database_url": "postgresql://example",
                    "store_type": "database",
                }
            )
        )

        with self.assertRaises(StoreError):
            store.list_table_fields("不存在的数据集")
