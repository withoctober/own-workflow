from __future__ import annotations

import base64
import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar
from urllib import error

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate
from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI

from workflow.core.env import env_value

T = TypeVar("T")


@dataclass
class AIConfig:
    api_key: str | None
    base_url: str
    model: str
    temperature: float
    timeout_seconds: int
    max_retries: int
    retry_backoff_seconds: int


@dataclass
class ChainResult(Generic[T]):
    value: T
    messages: list[BaseMessage]
    raw_text: str


def ai_config(root: Path, defaults: dict[str, Any] | None = None) -> AIConfig:
    defaults = defaults or {}
    return AIConfig(
        api_key=env_value("OPENAI_API_KEY", root),
        base_url=env_value("OPENAI_BASE_URL", root) or "https://api.openai.com/v1",
        model=env_value("OPENAI_MODEL", root) or str(defaults.get("model", "gpt-4.1-mini")),
        temperature=float(defaults.get("temperature", 0.7)),
        timeout_seconds=int(defaults.get("timeout_seconds", 600)),
        max_retries=int(defaults.get("max_retries", 2)),
        retry_backoff_seconds=int(defaults.get("retry_backoff_seconds", 3)),
    )


def chat_model(root: Path, defaults: dict[str, Any] | None = None) -> ChatOpenAI:
    config = ai_config(root, defaults)
    if not config.api_key:
        raise RuntimeError("OPENAI_API_KEY 未配置")
    return ChatOpenAI(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        temperature=config.temperature,
        timeout=config.timeout_seconds,
        max_retries=config.max_retries,
    )


def build_prompt_context(values: dict[str, Any]) -> str:
    if not values:
        return ""
    lines = [
        "# 运行时输入",
        "",
        "以下内容是本轮流程执行时提供给模型的真实输入数据。请结合这些输入，严格遵循后续“原始模板原文”中的角色、约束、输出要求和执行顺序。",
        "",
    ]
    for key, value in values.items():
        lines.append(f"## {key}")
        lines.append("")
        if isinstance(value, (dict, list)):
            lines.append(json.dumps(value, ensure_ascii=False, indent=2))
        else:
            lines.append(str(value))
        lines.append("")
    return "\n".join(lines).strip()


def build_output_contract_message(contract: dict[str, Any] | None) -> str:
    if not contract:
        return ""
    return "\n".join(
        [
            "# 结构化输出要求",
            "",
            "最终回复必须是合法 JSON，且只能输出 JSON 本身，不要输出解释、标题、前后缀或代码块围栏。",
            "请严格满足以下输出契约：",
            "",
            json.dumps(contract, ensure_ascii=False, indent=2),
        ]
    ).strip()


def build_user_message_content(text: str, image_urls: list[str] | None = None) -> str | list[dict[str, Any]]:
    normalized_urls: list[str] = []
    seen: set[str] = set()
    for item in image_urls or []:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized_urls.append(value)

    if not normalized_urls:
        return text

    parts: list[dict[str, Any]] = []
    if text.strip():
        parts.append({"type": "text", "text": text})
    for url in normalized_urls:
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return parts


def build_messages(
    *,
    prompt: str,
    template_values: dict[str, Any] | None = None,
    output_contract: dict[str, Any] | None = None,
    extra_text: str = "",
    extra_images: list[str] | None = None,
) -> list[BaseMessage]:
    prompt_parts: list[Any] = []
    values: dict[str, str] = {}

    if prompt.strip():
        prompt_parts.append(HumanMessagePromptTemplate.from_template("{raw_prompt}"))
        values["raw_prompt"] = f"# 原始模板原文\n\n{prompt}"

    prompt_context = build_prompt_context(template_values or {})
    if prompt_context:
        prompt_parts.append(HumanMessagePromptTemplate.from_template("{prompt_context}"))
        values["prompt_context"] = prompt_context

    contract_message = build_output_contract_message(output_contract)
    if contract_message:
        prompt_parts.append(HumanMessagePromptTemplate.from_template("{output_contract}"))
        values["output_contract"] = contract_message

    messages: list[BaseMessage] = []
    if prompt_parts:
        messages.extend(ChatPromptTemplate.from_messages(prompt_parts).invoke(values).messages)

    if extra_text.strip() or extra_images:
        messages.append(HumanMessage(content=build_user_message_content(extra_text, extra_images)))

    return messages


def build_message_trace(messages: list[Any]) -> str:
    sections: list[str] = []
    for index, message in enumerate(messages, start=1):
        if isinstance(message, BaseMessage):
            role = message.type
            content = message.content
        elif isinstance(message, dict):
            role = str(message.get("role", "user"))
            content = message.get("content", "")
        else:
            role = type(message).__name__
            content = str(message)

        rendered = json.dumps(content, ensure_ascii=False, indent=2) if isinstance(content, (dict, list)) else str(content)
        sections.append(f"## Message {index} [{role}]\n\n{rendered}".strip())
    return "\n\n---\n\n".join(sections).strip()


def _normalize_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    return ""


def _inline_image_url(url: str, *, timeout: int) -> str:
    normalized = url.strip()
    if not normalized.startswith(("http://", "https://")):
        return normalized

    request = urllib.request.Request(
        normalized,
        headers={"Accept": "image/*", "User-Agent": "Mozilla/5.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            content_type = response.headers.get_content_type() or "image/jpeg"
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"下载图片失败: HTTP {exc.code}; body={detail[:200]}") from exc
    except error.URLError as exc:
        raise ValueError(f"下载图片失败: {exc}") from exc
    encoded = base64.b64encode(body).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def prepare_messages_for_transport(messages: list[Any], *, timeout: int) -> list[Any]:
    prepared: list[Any] = []
    for message in messages:
        content = message.content if isinstance(message, BaseMessage) else message.get("content")
        if not isinstance(content, list):
            prepared.append(message)
            continue

        parts: list[dict[str, Any]] = []
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "image_url":
                parts.append(item)
                continue
            image_value = item.get("image_url")
            if isinstance(image_value, dict):
                image_url = str(image_value.get("url", "")).strip()
                detail = dict(image_value)
            else:
                image_url = str(image_value).strip()
                detail = {}
            if not image_url:
                parts.append(item)
                continue
            detail["url"] = _inline_image_url(image_url, timeout=timeout)
            parts.append({**item, "image_url": detail})

        if isinstance(message, BaseMessage):
            prepared.append(message.model_copy(update={"content": parts}))
        else:
            prepared.append({**message, "content": parts})
    return prepared


def invoke_chat_model(
    root: Path,
    *,
    messages: list[Any],
    defaults: dict[str, Any] | None = None,
) -> str:
    config = ai_config(root, defaults)
    payload_messages = prepare_messages_for_transport(messages, timeout=min(config.timeout_seconds, 120))
    response = chat_model(root, defaults).invoke(payload_messages)
    content = _normalize_content(response.content)
    if not content.strip():
        raise ValueError("LLM 响应内容为空")
    return content.strip()


def invoke_text_chain(
    root: Path,
    *,
    prompt: str,
    template_values: dict[str, Any] | None = None,
    extra_text: str = "",
    extra_images: list[str] | None = None,
    defaults: dict[str, Any] | None = None,
) -> ChainResult[str]:
    messages = build_messages(
        prompt=prompt,
        template_values=template_values,
        extra_text=extra_text,
        extra_images=extra_images,
    )
    config = ai_config(root, defaults)
    prepared_messages = prepare_messages_for_transport(messages, timeout=min(config.timeout_seconds, 120))
    chain = RunnableLambda(lambda _: prepared_messages) | chat_model(root, defaults) | StrOutputParser()
    text = str(chain.invoke({})).strip()
    if not text:
        raise ValueError("LLM 响应内容为空")
    return ChainResult(value=text, messages=messages, raw_text=text)


def invoke_json_chain(
    root: Path,
    *,
    prompt: str,
    template_values: dict[str, Any] | None = None,
    output_contract: dict[str, Any] | None = None,
    extra_text: str = "",
    extra_images: list[str] | None = None,
    defaults: dict[str, Any] | None = None,
    pydantic_object: type[Any] | None = None,
) -> ChainResult[Any]:
    parser = JsonOutputParser(pydantic_object=pydantic_object)
    parser_instructions = getattr(parser, "get_format_instructions", lambda: "")()
    composed_extra_text = extra_text.strip()
    if parser_instructions:
        composed_extra_text = (
            f"{composed_extra_text}\n\n# 输出格式要求\n\n{parser_instructions}".strip()
            if composed_extra_text
            else f"# 输出格式要求\n\n{parser_instructions}"
        )

    messages = build_messages(
        prompt=prompt,
        template_values=template_values,
        output_contract=output_contract,
        extra_text=composed_extra_text,
        extra_images=extra_images,
    )
    config = ai_config(root, defaults)
    prepared_messages = prepare_messages_for_transport(messages, timeout=min(config.timeout_seconds, 120))
    text_chain = RunnableLambda(lambda _: prepared_messages) | chat_model(root, defaults) | StrOutputParser()
    raw_text = str(text_chain.invoke({})).strip()
    value = parser.invoke(_strip_fence(raw_text))
    return ChainResult(value=value, messages=messages, raw_text=raw_text)


def _strip_fence(content: str, language: str | None = None) -> str:
    pattern = r"^```(?:%s)?\s*(.*?)\s*```$" % (language or "[a-zA-Z0-9_-]*")
    fenced = re.match(pattern, content.strip(), re.S)
    if fenced:
        return fenced.group(1).strip()
    return content.strip()


def parse_json_output(content: str) -> Any:
    text = _strip_fence(content, "json")
    try:
        return JsonOutputParser().parse(text)
    except Exception:
        return JsonOutputParser().parse(_strip_fence(content))


def parse_document_output(content: str) -> str:
    text = content.strip()
    if not text:
        raise ValueError("empty output")
    try:
        payload = parse_json_output(text)
    except Exception:
        payload = None
    if isinstance(payload, dict):
        markdown = str(payload.get("markdown", "")).strip()
        if markdown:
            return markdown
    text = _strip_fence(text)
    if not text:
        raise ValueError("empty output")
    return text


__all__ = [
    "AIConfig",
    "ai_config",
    "build_message_trace",
    "build_messages",
    "build_output_contract_message",
    "build_prompt_context",
    "build_user_message_content",
    "ChainResult",
    "chat_model",
    "invoke_chat_model",
    "invoke_json_chain",
    "invoke_text_chain",
    "parse_document_output",
    "parse_json_output",
    "prepare_messages_for_transport",
]
