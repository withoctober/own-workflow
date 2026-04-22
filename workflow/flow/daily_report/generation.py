from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from workflow.core.ai import ChainResult, invoke_json_chain
from workflow.core.prompting import prepare_prompt_inputs

DAILY_REPORT_PROMPT = "workflow/flow/daily_report/prompts/generate.md"


class DailyReportOutput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    today_topic: str = Field(alias="今日选题")
    content_type: str = Field(alias="内容类型")
    title_notes: str = Field(alias="标题说明")
    body_notes: str = Field(alias="正文说明")
    cover_and_image_notes: str = Field(alias="封面及配图说明")


def _normalize_daily_report_payload(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "today_topic": str(payload.get("today_topic", payload.get("今日选题", ""))).strip(),
        "content_type": str(payload.get("content_type", payload.get("内容类型", ""))).strip(),
        "title_notes": str(payload.get("title_notes", payload.get("标题说明", ""))).strip(),
        "body_notes": str(payload.get("body_notes", payload.get("正文说明", ""))).strip(),
        "cover_and_image_notes": str(payload.get("cover_and_image_notes", payload.get("封面及配图说明", ""))).strip(),
    }


def generate_daily_report_record(root, values: dict[str, Any]) -> ChainResult[dict[str, Any]]:
    prompt, context_values = prepare_prompt_inputs(root, DAILY_REPORT_PROMPT, values, template_keys=("today",))
    result = invoke_json_chain(
        root,
        prompt=prompt,
        template_values=context_values,
        pydantic_object=DailyReportOutput,
    )
    payload = result.value
    if isinstance(payload, DailyReportOutput):
        data = payload.model_dump()
    elif isinstance(payload, dict):
        data = _normalize_daily_report_payload(payload)
    else:
        raise ValueError("日报输出不是 JSON object")
    return ChainResult(value=data, messages=result.messages, raw_text=result.raw_text)
