from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from workflow.core.ai import ChainResult, invoke_json_chain
from workflow.core.prompting import prepare_prompt_inputs
from workflow.flow.content_create.utils import normalize_copy_payload, normalize_image_prompt_payload

ORIGINAL_COPY_PROMPT = "workflow/flow/content_create/prompts/original_copy.md"
ORIGINAL_IMAGE_PROMPT = "workflow/flow/content_create/prompts/original_image.md"
REWRITE_COPY_PROMPT = "workflow/flow/content_create/prompts/rewrite_copy.md"
REWRITE_IMAGE_PROMPT = "workflow/flow/content_create/prompts/rewrite_image.md"


class CopyOutput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str = Field(default="", validation_alias=AliasChoices("title", "标题"))
    content: str = Field(default="", validation_alias=AliasChoices("content", "正文", "正文内容"))
    tags: str = Field(default="", validation_alias=AliasChoices("tags", "标签"))


class ImagePromptsOutput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    cover_prompt: str = Field(default="", validation_alias=AliasChoices("cover_prompt", "封面提示词"))
    image_prompts: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("image_prompts", "配图提示词"),
    )


def _normalize_copy_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, CopyOutput):
        return payload.model_dump()
    if isinstance(payload, dict):
        return normalize_copy_payload(payload)
    raise ValueError("文案输出不是 JSON object")


def _normalize_image_prompts(payload: Any) -> dict[str, Any]:
    if isinstance(payload, ImagePromptsOutput):
        return payload.model_dump()
    if isinstance(payload, dict):
        return normalize_image_prompt_payload(payload)
    raise ValueError("配图提示词输出不是 JSON object")


def generate_original_copy(root, values: dict[str, Any]) -> ChainResult[dict[str, Any]]:
    prompt, context_values = prepare_prompt_inputs(root, ORIGINAL_COPY_PROMPT, values)
    result = invoke_json_chain(
        root,
        prompt=prompt,
        template_values=context_values,
        pydantic_object=CopyOutput,
    )
    payload = _normalize_copy_payload(result.value)
    return ChainResult(value=payload, messages=result.messages, raw_text=result.raw_text)


def generate_original_image_prompts(root, values: dict[str, Any]) -> ChainResult[dict[str, Any]]:
    prompt, context_values = prepare_prompt_inputs(root, ORIGINAL_IMAGE_PROMPT, values)
    result = invoke_json_chain(
        root,
        prompt=prompt,
        template_values=context_values,
        pydantic_object=ImagePromptsOutput,
    )
    payload = _normalize_image_prompts(result.value)
    return ChainResult(value=payload, messages=result.messages, raw_text=result.raw_text)


def generate_rewrite_copy(root, values: dict[str, Any]) -> ChainResult[dict[str, Any]]:
    prompt, context_values = prepare_prompt_inputs(root, REWRITE_COPY_PROMPT, values)
    result = invoke_json_chain(
        root,
        prompt=prompt,
        template_values=context_values,
        pydantic_object=CopyOutput,
    )
    payload = _normalize_copy_payload(result.value)
    return ChainResult(value=payload, messages=result.messages, raw_text=result.raw_text)


def generate_rewrite_image_prompts(
    root,
    values: dict[str, Any],
    *,
    extra_text: str = "",
    extra_images: list[str] | None = None,
) -> ChainResult[dict[str, Any]]:
    prompt, context_values = prepare_prompt_inputs(root, REWRITE_IMAGE_PROMPT, values)
    result = invoke_json_chain(
        root,
        prompt=prompt,
        template_values=context_values,
        pydantic_object=ImagePromptsOutput,
        extra_text=extra_text,
        extra_images=extra_images,
    )
    payload = _normalize_image_prompts(result.value)
    return ChainResult(value=payload, messages=result.messages, raw_text=result.raw_text)
