from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock

from workflow.store.feishu import FeishuResourceConfig, FeishuStore


def build_store() -> FeishuStore:
    config = FeishuResourceConfig(
        path=Path("/tmp/test-feishu-store.json"),
        payload={
            "tables": {
                "生成作品库": {
                    "app_token": "app_token",
                    "table_id": "table_id",
                }
            },
            "docs": {},
        },
    )
    return FeishuStore(Path("."), config)


class FeishuStoreTest(unittest.TestCase):
    def test_write_table_strips_leading_blank_lines_before_create(self) -> None:
        store = build_store()
        store._request_json = MagicMock(return_value={"data": {}})

        store.write_table(
            "生成作品库",
            [
                {
                    "标题": "\n\n标题",
                    "正文": " \n\t\n正文首行",
                    "说明": "  保留缩进",
                    "nested": {"content": "\n嵌套内容"},
                    "items": ["\n条目A", {"text": "\n\n条目B"}],
                }
            ],
            mode="append_latest",
        )

        payload = store._request_json.call_args.kwargs["payload"]
        self.assertEqual(
            payload["records"],
            [
                {
                    "fields": {
                        "标题": "标题",
                        "正文": "正文首行",
                        "说明": "  保留缩进",
                        "nested": {"content": "嵌套内容"},
                        "items": ["条目A", {"text": "条目B"}],
                    }
                }
            ],
        )

    def test_update_table_records_strips_leading_blank_lines_before_update(self) -> None:
        store = build_store()
        store._request_json = MagicMock(return_value={"data": {}})

        store.update_table_records(
            "生成作品库",
            [
                {
                    "record_id": "rec123",
                    "标题": "\n\n待更新标题",
                    "正文": "\r\n\r\n待更新正文",
                }
            ],
        )

        payload = store._request_json.call_args.kwargs["payload"]
        self.assertEqual(
            payload["records"],
            [
                {
                    "record_id": "rec123",
                    "fields": {
                        "标题": "待更新标题",
                        "正文": "待更新正文",
                    },
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
