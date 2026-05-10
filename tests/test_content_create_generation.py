from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from workflow.flow.content_create.generation import generate_original_image_prompts


class ContentCreateGenerationTest(unittest.TestCase):
    def test_generate_original_image_prompts_falls_back_to_raw_text_when_cover_prompt_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            with patch(
                "workflow.flow.content_create.generation.invoke_json_chain",
                return_value=SimpleNamespace(
                    value={"cover_prompt": "", "image_prompts": []},
                    messages=["ok"],
                    raw_text='{"image_prompts":["封面提示词","第二张提示词"]}',
                ),
            ):
                result = generate_original_image_prompts(
                    root,
                    {
                        "marketing_plan": "marketing-plan",
                        "daily_report": {"日期": "2026-05-11"},
                        "draft_copy": {"title": "标题", "content": "正文", "tags": "#标签"},
                        "topic_context": {},
                        "additional_instruction": "",
                    },
                )

        self.assertEqual(result.value["cover_prompt"], "封面提示词")
        self.assertEqual(result.value["image_prompts"], ["第二张提示词"])


if __name__ == "__main__":
    unittest.main()
