from __future__ import annotations

import unittest
import urllib.parse

from workflow.flow.content_collect.generation import IndustryKeywordsOutput, TopicRow
from workflow.flow.content_create.generation import CopyOutput, ImagePromptsOutput
from workflow.flow.content_create.utils import (
    extract_profile_user_id,
    normalize_source_post,
    parse_copy_payload,
    parse_image_prompt_payload,
)
from workflow.flow.daily_report.generation import DailyReportOutput


class GenerationAliasTest(unittest.TestCase):
    def test_industry_keywords_supports_chinese_aliases(self) -> None:
        payload = IndustryKeywordsOutput.model_validate(
            {
                "关键词": "二手交易",
                "行业关键词": "同城闲置",
            }
        )
        self.assertEqual(payload.keywords, "二手交易")
        self.assertEqual(
            payload.model_dump(),
            {
                "keywords": "二手交易",
                "industry_keywords": "同城闲置",
            },
        )
        self.assertEqual(
            payload.model_dump(by_alias=True),
            {
                "关键词": "二手交易",
                "行业关键词": "同城闲置",
            },
        )

    def test_topic_row_supports_english_field_names(self) -> None:
        payload = TopicRow.model_validate(
            {
                "hit_title": "标题",
                "scenario": "场景",
                "pain_point": "痛点",
                "solution": "方案",
                "xiaohongshu_value": "价值",
                "topic_idea": "思路",
            }
        )
        self.assertEqual(
            payload.model_dump(),
            {
                "hit_title": "标题",
                "scenario": "场景",
                "pain_point": "痛点",
                "solution": "方案",
                "xiaohongshu_value": "价值",
                "topic_idea": "思路",
            },
        )
        self.assertEqual(
            payload.model_dump(by_alias=True),
            {
                "爆款标题": "标题",
                "具体场景": "场景",
                "用户痛点": "痛点",
                "解决方案": "方案",
                "小红书种草价值点": "价值",
                "小红书选题思路": "思路",
            },
        )

    def test_daily_report_supports_chinese_aliases(self) -> None:
        payload = DailyReportOutput.model_validate(
            {
                "今日选题": "选题",
                "内容类型": "图文",
                "标题说明": "标题说明",
                "正文说明": "正文说明",
                "封面及配图说明": "封面说明",
            }
        )
        self.assertEqual(payload.today_topic, "选题")
        self.assertEqual(
            payload.model_dump(),
            {
                "today_topic": "选题",
                "content_type": "图文",
                "title_notes": "标题说明",
                "body_notes": "正文说明",
                "cover_and_image_notes": "封面说明",
            },
        )
        self.assertEqual(
            payload.model_dump(by_alias=True),
            {
                "今日选题": "选题",
                "内容类型": "图文",
                "标题说明": "标题说明",
                "正文说明": "正文说明",
                "封面及配图说明": "封面说明",
            },
        )

    def test_copy_output_supports_chinese_aliases(self) -> None:
        payload = CopyOutput.model_validate(
            {
                "标题": "标题",
                "正文内容": "正文",
                "标签": "#标签1 #标签2",
            }
        )
        self.assertEqual(
            payload.model_dump(),
            {
                "title": "标题",
                "content": "正文",
                "tags": "#标签1 #标签2",
            },
        )

    def test_image_prompts_output_supports_chinese_aliases(self) -> None:
        payload = ImagePromptsOutput.model_validate(
            {
                "封面提示词": "封面提示词",
                "配图提示词": ["配图1", "配图2"],
            }
        )
        self.assertEqual(
            payload.model_dump(),
            {
                "cover_prompt": "封面提示词",
                "image_prompts": ["配图1", "配图2"],
            },
        )

    def test_image_prompts_output_rejects_empty_cover_prompt(self) -> None:
        with self.assertRaisesRegex(ValueError, "cover_prompt"):
            parse_image_prompt_payload(
                """
                {
                  "cover_prompt": "",
                  "image_prompts": []
                }
                """
            )

    def test_parse_copy_payload_keeps_english_contract(self) -> None:
        payload = parse_copy_payload(
            """
            {
              "copy": {
                "标题": "新标题",
                "正文": "正文内容",
                "标签": ["#a", "#b"]
              }
            }
            """
        )
        self.assertEqual(
            payload,
            {
                "title": "新标题",
                "content": "正文内容",
                "tags": "#a #b",
            },
        )

    def test_parse_image_prompt_payload_keeps_english_contract(self) -> None:
        payload = parse_image_prompt_payload(
            """
            {
              "image_prompts": {
                "封面提示词": "封面",
                "配图提示词": "第2张 配图二\\n第3张 配图三"
              }
            }
            """
        )
        self.assertEqual(
            payload,
            {
                "cover_prompt": "封面",
                "image_prompts": ["第2张 配图二", "第3张 配图三"],
            },
        )

    def test_normalize_source_post_uses_english_keys(self) -> None:
        payload = normalize_source_post(
            {
                "note_id": "123",
                "type": "normal",
                "title": "标题",
                "desc": "正文 #标签",
                "liked_count": 12,
                "collected_count": 8,
                "comments_count": 3,
                "shared_count": 1,
                "user": {"nickname": "作者", "id": "u1"},
                "images_list": ["https://img/cover.jpg", "https://img/detail.jpg"],
            },
            "https://www.xiaohongshu.com/explore/123",
        )
        self.assertEqual(payload["source_url"], "https://www.xiaohongshu.com/explore/123")
        self.assertEqual(payload["note_id"], "123")
        self.assertEqual(payload["author_name"], "作者")
        self.assertEqual(payload["title"], "标题")
        self.assertEqual(payload["content"], "正文 #标签")
        self.assertEqual(payload["tags"], "#标签")
        self.assertEqual(payload["cover_url"], "https://img/cover.jpg")
        self.assertEqual(payload["image_urls"], ["https://img/cover.jpg", "https://img/detail.jpg"])
        self.assertEqual(payload["image_count"], 2)

    def test_extract_profile_user_id_from_final_url(self) -> None:
        final_url = "https://www.xiaohongshu.com/user/profile/636a06e0000000001f016108?xsec_source=app_share"
        self.assertEqual(extract_profile_user_id(final_url), "636a06e0000000001f016108")

    def test_extract_profile_user_id_from_encoded_query(self) -> None:
        profile_url = "https://www.xiaohongshu.com/user/profile/636a06e0000000001f016108?foo=bar"
        final_url = f"https://example.com/redirect?target={urllib.parse.quote(profile_url, safe='')}"
        self.assertEqual(extract_profile_user_id(final_url), "636a06e0000000001f016108")


if __name__ == "__main__":
    unittest.main()
