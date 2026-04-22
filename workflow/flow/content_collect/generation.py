from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from workflow.core.ai import ChainResult, invoke_json_chain, invoke_text_chain
from workflow.core.prompting import prepare_prompt_inputs

INDUSTRY_KEYWORDS_PROMPT = "workflow/flow/content_collect/prompts/industry_keywords.md"
INDUSTRY_REPORT_PROMPT = "workflow/flow/content_collect/prompts/industry_report.md"
MARKETING_PLAN_PROMPT = "workflow/flow/content_collect/prompts/marketing_plan.md"
KEYWORD_MATRIX_PROMPT = "workflow/flow/content_collect/prompts/keyword_matrix.md"
TOPIC_BANK_PROMPT = "workflow/flow/content_collect/prompts/topic_bank.md"


class IndustryKeywordsOutput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    keywords: str = Field(default="", alias="关键词")
    industry_keywords: str = Field(default="", alias="行业关键词")


class TopicRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    hit_title: str = Field(default="", alias="爆款标题")
    scenario: str = Field(default="", alias="具体场景")
    pain_point: str = Field(default="", alias="用户痛点")
    solution: str = Field(default="", alias="解决方案")
    xiaohongshu_value: str = Field(default="", alias="小红书种草价值点")
    topic_idea: str = Field(default="", alias="小红书选题思路")


class TopicBankOutput(BaseModel):
    topics: list[TopicRow] = Field(default_factory=list)


def _normalize_industry_keywords_payload(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "keywords": str(payload.get("keywords", payload.get("关键词", ""))).strip(),
        "industry_keywords": str(payload.get("industry_keywords", payload.get("行业关键词", ""))).strip(),
    }


def _normalize_topic_row(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "hit_title": str(payload.get("hit_title", payload.get("爆款标题", ""))).strip(),
        "scenario": str(payload.get("scenario", payload.get("具体场景", ""))).strip(),
        "pain_point": str(payload.get("pain_point", payload.get("用户痛点", ""))).strip(),
        "solution": str(payload.get("solution", payload.get("解决方案", ""))).strip(),
        "xiaohongshu_value": str(payload.get("xiaohongshu_value", payload.get("小红书种草价值点", ""))).strip(),
        "topic_idea": str(payload.get("topic_idea", payload.get("小红书选题思路", ""))).strip(),
    }


def generate_industry_keywords(root, values: dict[str, Any]) -> ChainResult[dict[str, Any]]:
    prompt, context_values = prepare_prompt_inputs(root, INDUSTRY_KEYWORDS_PROMPT, values)
    result = invoke_json_chain(
        root,
        prompt=prompt,
        template_values=context_values,
        pydantic_object=IndustryKeywordsOutput,
    )
    payload = result.value
    if isinstance(payload, IndustryKeywordsOutput):
        data = payload.model_dump()
    elif isinstance(payload, dict):
        data = _normalize_industry_keywords_payload(payload)
    else:
        raise ValueError("行业关键词输出不是 JSON object")
    return ChainResult(value=data, messages=result.messages, raw_text=result.raw_text)


def generate_industry_report(root, values: dict[str, Any]) -> ChainResult[str]:
    prompt, context_values = prepare_prompt_inputs(root, INDUSTRY_REPORT_PROMPT, values)
    return invoke_text_chain(root, prompt=prompt, template_values=context_values)


def generate_marketing_plan(root, values: dict[str, Any]) -> ChainResult[str]:
    prompt, context_values = prepare_prompt_inputs(root, MARKETING_PLAN_PROMPT, values)
    return invoke_text_chain(root, prompt=prompt, template_values=context_values)


def generate_keyword_matrix(root, values: dict[str, Any]) -> ChainResult[str]:
    prompt, context_values = prepare_prompt_inputs(root, KEYWORD_MATRIX_PROMPT, values)
    return invoke_text_chain(root, prompt=prompt, template_values=context_values)


def generate_topic_bank(root, values: dict[str, Any]) -> ChainResult[list[dict[str, str]]]:
    prompt, context_values = prepare_prompt_inputs(root, TOPIC_BANK_PROMPT, values)
    result = invoke_json_chain(
        root,
        prompt=prompt,
        template_values=context_values,
        pydantic_object=TopicBankOutput,
    )
    payload = result.value
    if isinstance(payload, TopicBankOutput):
        topics = [row.model_dump() for row in payload.topics]
    elif isinstance(payload, dict):
        topics = [_normalize_topic_row(row) for row in payload.get("topics", []) if isinstance(row, dict)]
    else:
        raise ValueError("选题库输出不是 JSON object")
    return ChainResult(value=topics, messages=result.messages, raw_text=result.raw_text)
