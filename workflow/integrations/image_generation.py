from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from workflow.core.ai import tenant_api_value
from workflow.core.env import env_value
from workflow.integrations import build_s3_uploader
from workflow.store import StoreError


ARK_IMAGE_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
DEFAULT_IMAGE_PROVIDER = "ark"
DEFAULT_IMAGE_MODEL = "doubao-seedream-5-0-260128"
DEFAULT_IMAGE_SIZE = "1728x2304"


def truncate_preview(text: str, max_chars: int = 300) -> str:
    """Returns a shortened preview for remote error bodies.

    Args:
        text: Raw response text.
        max_chars: Maximum characters to keep.

    Returns:
        A trimmed preview string.
    """
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def resolve_image_provider(context: dict[str, Any]) -> str:
    """Resolves the image provider name from runtime context.

    Args:
        context: Flow image-generation context.

    Returns:
        Normalized provider name. Defaults to ``ark``.
    """
    step = context.get("step", {})
    step_provider = str(step.get("image_provider", "")).strip().lower()
    if step_provider:
        return step_provider

    tenant_config = context.get("tenant_config")
    tenant_provider = tenant_api_value(tenant_config, "IMAGE_PROVIDER").lower()
    if tenant_provider:
        return tenant_provider

    root = Path(str(context["root"])).resolve()
    env_provider = str(env_value("IMAGE_PROVIDER", root) or "").strip().lower()
    return env_provider or DEFAULT_IMAGE_PROVIDER


def resolve_image_api_key(context: dict[str, Any], provider: str) -> str:
    """Resolves the API key for the selected image provider.

    Args:
        context: Flow image-generation context.
        provider: Selected provider name.

    Returns:
        Provider API key.

    Raises:
        StoreError: If the provider is unsupported or credentials are missing.
    """
    root = Path(str(context["root"])).resolve()
    tenant_config = context.get("tenant_config")

    if provider == "ark":
        if tenant_config is not None and getattr(tenant_config, "api_mode", "") == "custom":
            api_key = tenant_api_value(tenant_config, "ARK_API_KEY")
        else:
            api_key = env_value("ARK_API_KEY", root)
        if not api_key:
            raise StoreError("缺少 ARK_API_KEY，无法执行实际出图")
        return api_key

    raise StoreError(f"不支持的图片 provider: {provider}")


def build_image_payload(context: dict[str, Any], prompt: str, provider: str) -> dict[str, Any]:
    """Builds the provider-specific image request payload.

    Args:
        context: Flow image-generation context.
        prompt: Prompt text.
        provider: Selected provider name.

    Returns:
        Provider request payload.

    Raises:
        StoreError: If the provider is unsupported.
    """
    step = context.get("step", {})
    if provider == "ark":
        return {
            "model": step.get("image_model", DEFAULT_IMAGE_MODEL),
            "prompt": prompt,
            "sequential_image_generation": step.get("sequential_image_generation", "disabled"),
            "response_format": "url",
            "size": step.get("image_size", DEFAULT_IMAGE_SIZE),
            "stream": False,
            "watermark": bool(step.get("watermark", False)),
        }
    raise StoreError(f"不支持的图片 provider: {provider}")


def request_ark_image(api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Calls the Ark image API.

    Args:
        api_key: Ark API key.
        payload: Ark request payload.

    Returns:
        Parsed Ark JSON response.

    Raises:
        StoreError: If the request fails or response shape is invalid.
    """
    body = json.dumps(payload).encode("utf-8")
    request_obj = urllib.request.Request(
        ARK_IMAGE_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(request_obj, timeout=600) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise StoreError(f"图片接口调用失败: HTTP {exc.code}; body={truncate_preview(detail, 500)}") from exc
    except urllib.error.URLError as exc:
        raise StoreError(f"图片接口请求失败: {exc}") from exc
    if not isinstance(result, dict):
        raise StoreError("图片接口返回不是 JSON object")
    return result


def request_image_with_provider(provider: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Dispatches the image request to the selected provider.

    Args:
        provider: Selected provider name.
        api_key: Provider API key.
        payload: Provider request payload.

    Returns:
        Provider JSON response.

    Raises:
        StoreError: If the provider is unsupported.
    """
    if provider == "ark":
        return request_ark_image(api_key, payload)
    raise StoreError(f"不支持的图片 provider: {provider}")


def extract_image_urls(response: dict[str, Any], provider: str) -> list[str]:
    """Extracts image URLs from a provider response.

    Args:
        response: Provider response payload.
        provider: Selected provider name.

    Returns:
        Generated image URLs.

    Raises:
        StoreError: If the provider is unsupported.
    """
    if provider == "ark":
        urls: list[str] = []
        for item in response.get("data", []):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "")).strip()
            if url:
                urls.append(url)
        return urls
    raise StoreError(f"不支持的图片 provider: {provider}")


def build_generated_image_object_key(batch_id: str, index: int, prompt: str, variant_index: int = 0) -> str:
    """Builds the object key for generated image uploads.

    Args:
        batch_id: Workflow batch identifier.
        index: Prompt index.
        prompt: Prompt text.
        variant_index: Variant index returned by the provider.

    Returns:
        S3/COS object key without file extension.
    """
    normalized_batch_id = str(batch_id).strip() or "manual"
    prompt_hash = hashlib.sha1(prompt.strip().encode("utf-8")).hexdigest()[:12]
    role = "cover" if index == 0 else f"image-{index:02d}"
    return f"generated-images/{normalized_batch_id}/{index:02d}-{role}-{variant_index:02d}-{prompt_hash}"


def upload_generated_images_to_s3(
    context: dict[str, Any],
    prompts: list[str],
    urls_by_prompt: list[list[str]],
) -> dict[str, Any]:
    """Uploads generated image URLs to object storage.

    Args:
        context: Flow image-generation context.
        prompts: Prompt list in order.
        urls_by_prompt: Provider source URLs grouped by prompt.

    Returns:
        Normalized upload payload with cover and image URLs.
    """
    root = Path(str(context["root"])).resolve()
    tenant_config = context.get("tenant_config")
    uploader = build_s3_uploader(root, tenant_config)
    batch_id = str(context.get("batch_id", "")).strip()

    uploaded_urls_by_prompt: list[list[str]] = []
    uploaded_results: list[dict[str, Any]] = []
    for index, (prompt, source_urls) in enumerate(zip(prompts, urls_by_prompt, strict=False)):
        prompt_uploaded_urls: list[str] = []
        uploaded_objects: list[dict[str, Any]] = []
        for variant_index, source_url in enumerate(source_urls):
            uploaded = uploader.upload_from_url(
                str(source_url).strip(),
                build_generated_image_object_key(batch_id, index, prompt, variant_index),
            )
            prompt_uploaded_urls.append(uploaded.url)
            uploaded_objects.append(
                {
                    "bucket": uploaded.bucket,
                    "key": uploaded.key,
                    "url": uploaded.url,
                    "etag": uploaded.etag,
                    "content_type": uploaded.content_type,
                    "size": uploaded.size,
                    "source_url": str(source_url).strip(),
                }
            )
        uploaded_urls_by_prompt.append(prompt_uploaded_urls)
        uploaded_results.append(
            {
                "prompt": prompt,
                "source_urls": [str(item).strip() for item in source_urls if str(item).strip()],
                "uploaded": uploaded_objects,
            }
        )

    cover_url = uploaded_urls_by_prompt[0][0] if uploaded_urls_by_prompt and uploaded_urls_by_prompt[0] else ""
    image_urls = [item[0] for item in uploaded_urls_by_prompt[1:] if item]
    return {
        "cover_url": cover_url,
        "image_urls": image_urls,
        "uploaded_results": uploaded_results,
    }


def generate_images(context: dict[str, Any], prompts: list[str]) -> dict[str, Any]:
    """Generates images with the selected provider and uploads them.

    Args:
        context: Flow image-generation context.
        prompts: Prompt list where index 0 is the cover.

    Returns:
        Normalized image payload used by the content-create flow.
    """
    provider = resolve_image_provider(context)
    api_key = resolve_image_api_key(context, provider)

    raw_results: list[dict[str, Any]] = []
    urls_by_prompt: list[list[str]] = []
    for prompt in prompts:
        payload = build_image_payload(context, prompt, provider)
        response = request_image_with_provider(provider, api_key, payload)
        urls = extract_image_urls(response, provider)
        if not urls:
            raise StoreError("图片接口未返回 URL")
        urls_by_prompt.append(urls)
        raw_results.append(
            {
                "provider": provider,
                "prompt": prompt,
                "response": response,
                "urls": urls,
            }
        )

    uploaded_payload = upload_generated_images_to_s3(context, prompts, urls_by_prompt)
    return {
        "cover_url": uploaded_payload["cover_url"],
        "image_urls": uploaded_payload["image_urls"],
        "raw_results": raw_results,
        "uploaded_results": uploaded_payload["uploaded_results"],
    }


__all__ = [
    "build_generated_image_object_key",
    "build_image_payload",
    "extract_image_urls",
    "generate_images",
    "request_ark_image",
    "request_image_with_provider",
    "resolve_image_api_key",
    "resolve_image_provider",
    "upload_generated_images_to_s3",
]
