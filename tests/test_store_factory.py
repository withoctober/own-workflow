from __future__ import annotations

import unittest
from pathlib import Path

from workflow.runtime.tenant import TenantRuntimeConfig
from workflow.store.database import DatabaseStore
from workflow.store.factory import build_store


class StoreFactoryTest(unittest.TestCase):
    def test_build_store_returns_database_store(self) -> None:
        store = build_store(
            Path("."),
            tenant_config=TenantRuntimeConfig(
                payload={
                    "tenant_id": "tenant-a",
                    "database_url": "postgresql://example",
                }
            ),
        )

        self.assertIsInstance(store, DatabaseStore)
