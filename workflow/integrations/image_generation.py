from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from workflow.core.ai import tenant_api_value
from workflow.core.env import env_value
from workflow.integrations import build_s3_uploader
from workflow.store import StoreError


ARK_IMAGE_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
DEFAULT_IMAGE_PROVIDER = "ark"
DEFAULT_ARK_IMAGE_MODEL = "doubao-seedream-5-0-260128"
DEFAULT_OPENAI_IMAGE_BASE_URL = "https://api.uniapi.io/v1"
DEFAULT_OPENAI_IMAGE_MODEL = "gpt-image-2"
DEFAULT_IMAGE_SIZE = "1728x2304"
DEFAULT_IMAGE_TIMEOUT_SECONDS = 600
DEFAULT_REFERENCE_IMAGE_FILENAME = "reference-image.png"


def truncate_preview(text: str, max_chars: int = 300) -> str:
    """Returns a shortened preview for remote error bodies."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _step_value(context: dict[str, Any], key: str) -> str:
    step = context.get("step", {})
    return str(step.get(key, "")).strip()


def _tenant_or_env_value(
    context: dict[str, Any],
    tenant_keys: tuple[str, ...],
    env_keys: tuple[str, ...],
) -> str:
    tenant_config = context.get("tenant_config")
    if tenant_config is not None and getattr(tenant_config, "api_mode", "") == "custom":
        for key in tenant_keys:
            value = tenant_api_value(tenant_config, key)
            if value:
                return value

    root = Path(str(context["root"])).resolve()
    for key in env_keys:
        value = str(env_value(key, root) or "").strip()
        if value:
            return value
    return ""


def resolve_image_provider(context: dict[str, Any]) -> str:
    """Resolves the image provider name from runtime context."""
    step_provider = _step_value(context, "image_provider").lower()
    if step_provider:
        return step_provider

    tenant_provider = _tenant_or_env_value(context, ("IMAGE_PROVIDER",), ("IMAGE_PROVIDER",)).lower()
    if tenant_provider:
        return tenant_provider
    return DEFAULT_IMAGE_PROVIDER


def resolve_image_api_key(context: dict[str, Any], provider: str) -> str:
    """Resolves the API key for the selected image provider."""
    if provider == "ark":
        api_key = _tenant_or_env_value(context, ("ARK_API_KEY",), ("ARK_API_KEY",))
        if not api_key:
            raise StoreError("missing ARK_API_KEY for image generation")
        return api_key

    if provider == "openai":
        api_key = _tenant_or_env_value(
            context,
            ("OPENAI_IMAGE_API_KEY", "OPENAI_API_KEY"),
            ("OPENAI_IMAGE_API_KEY", "OPENAI_API_KEY"),
        )
        if not api_key:
            raise StoreError("missing OPENAI_IMAGE_API_KEY or OPENAI_API_KEY for image generation")
        return api_key

    raise StoreError(f"unsupported image provider: {provider}")


def resolve_image_base_url(context: dict[str, Any], provider: str) -> str:
    """Resolves the base URL for OpenAI-compatible image providers."""
    if provider != "openai":
        return ""

    step_base_url = _step_value(context, "image_base_url")
    if step_base_url:
        return step_base_url

    base_url = _tenant_or_env_value(
        context,
        ("OPENAI_IMAGE_BASE_URL", "OPENAI_BASE_URL"),
        ("OPENAI_IMAGE_BASE_URL", "OPENAI_BASE_URL"),
    )
    return base_url or DEFAULT_OPENAI_IMAGE_BASE_URL


def resolve_image_model(context: dict[str, Any], provider: str) -> str:
    """Resolves the image model name for the selected provider."""
    step_model = _step_value(context, "image_model")
    if step_model:
        return step_model

    if provider == "ark":
        model = _tenant_or_env_value(context, ("ARK_IMAGE_MODEL",), ("ARK_IMAGE_MODEL",))
        return model or DEFAULT_ARK_IMAGE_MODEL

    if provider == "openai":
        model = _tenant_or_env_value(
            context,
            ("OPENAI_IMAGE_MODEL", "IMAGE_MODEL"),
            ("OPENAI_IMAGE_MODEL", "IMAGE_MODEL"),
        )
        return model or DEFAULT_OPENAI_IMAGE_MODEL

    raise StoreError(f"unsupported image provider: {provider}")


def build_image_payload(
    context: dict[str, Any],
    prompt: str,
    provider: str,
) -> dict[str, Any]:
    """Builds the provider-specific image request payload."""
    step = context.get("step", {})
    if provider == "ark":
        return {
            "model": resolve_image_model(context, provider),
            "prompt": prompt,
            "sequential_image_generation": step.get("sequential_image_generation", "disabled"),
            "response_format": "url",
            "size": step.get("image_size", DEFAULT_IMAGE_SIZE),
            "stream": False,
            "watermark": bool(step.get("watermark", False)),
        }
    if provider == "openai":
        payload: dict[str, Any] = {
            "model": resolve_image_model(context, provider),
            "prompt": prompt,
        }
        size = _step_value(context, "image_size")
        if size:
            payload["size"] = size
        return payload
    raise StoreError(f"unsupported image provider: {provider}")


def request_ark_image(api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Calls the Ark image API."""
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
        with urllib.request.urlopen(request_obj, timeout=DEFAULT_IMAGE_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise StoreError(f"image provider request failed: HTTP {exc.code}; body={truncate_preview(detail, 500)}") from exc
    except urllib.error.URLError as exc:
        raise StoreError(f"image provider request failed: {exc}") from exc
    if not isinstance(result, dict):
        raise StoreError("image provider response was not a JSON object")
    return result


def request_openai_image(
    api_key: str,
    base_url: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Calls an OpenAI-compatible image API and returns a sanitized response."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise StoreError("openai package is required for the openai image provider") from exc

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=DEFAULT_IMAGE_TIMEOUT_SECONDS,
        max_retries=2,
    )
    try:
        result = client.images.generate(**payload)
    except Exception as exc:  # pragma: no cover - provider-specific SDK errors vary by version
        detail = getattr(exc, "message", "") or str(exc)
        raise StoreError(f"openai image generation failed: {truncate_preview(detail, 500)}") from exc

    model_dump = getattr(result, "model_dump", None)
    raw_payload = model_dump(mode="json") if callable(model_dump) else {}
    data_items = raw_payload.get("data", []) if isinstance(raw_payload, dict) else []
    sanitized_items: list[dict[str, Any]] = []
    for item in data_items:
        if not isinstance(item, dict):
            continue
        entry: dict[str, Any] = {}
        url = str(item.get("url", "")).strip()
        if url:
            entry["url"] = url
        mime_type = str(item.get("mime_type", "")).strip()
        if mime_type:
            entry["mime_type"] = mime_type
        if str(item.get("b64_json", "")).strip():
            entry["has_b64_json"] = True
        sanitized_items.append(entry)

    return {
        "created": raw_payload.get("created") if isinstance(raw_payload, dict) else None,
        "data": sanitized_items,
        "_sdk_result": result,
    }


def _guess_filename_from_url(source_url: str, content_type: str) -> str:
    parsed = urllib.parse.urlsplit(source_url)
    candidate = Path(parsed.path).name.strip()
    if not candidate:
        candidate = DEFAULT_REFERENCE_IMAGE_FILENAME
    if Path(candidate).suffix:
        return candidate
    extension = mimetypes.guess_extension(content_type, strict=False) if content_type else ""
    if extension == ".jpe":
        extension = ".jpg"
    return f"{candidate}{extension or '.png'}"


def _decode_data_url_image(source_url: str) -> dict[str, Any]:
    normalized_source_url = str(source_url).strip()
    if "," not in normalized_source_url:
        raise StoreError("reference image data URL is invalid")

    header, encoded = normalized_source_url.split(",", 1)
    metadata = header[5:] if header.startswith("data:") else ""
    content_type = metadata.split(";", 1)[0].strip() or "image/png"
    is_base64 = ";base64" in metadata

    try:
        data = base64.b64decode(encoded) if is_base64 else urllib.parse.unquote_to_bytes(encoded)
    except (ValueError, TypeError) as exc:
        raise StoreError(f"reference image data URL decode failed: {exc}") from exc

    extension = mimetypes.guess_extension(content_type, strict=False) if content_type else ""
    if extension == ".jpe":
        extension = ".jpg"
    return {
        "source_url": normalized_source_url,
        "content_type": content_type,
        "filename": f"reference-image{extension or '.png'}",
        "data": data,
    }


def download_reference_image(source_url: str, *, timeout: int = DEFAULT_IMAGE_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Downloads a reference image and returns its bytes plus metadata."""
    normalized_source_url = str(source_url).strip()
    if normalized_source_url.startswith("data:image/"):
        return _decode_data_url_image(normalized_source_url)

    request_obj = urllib.request.Request(
        normalized_source_url,
        headers={
            "Accept": "image/*",
            "User-Agent": "OpenClaw-ImageEdit/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request_obj, timeout=timeout) as response:
            data = response.read()
            final_url = response.geturl()
            content_type = str(response.headers.get("Content-Type", "")).split(";", 1)[0].strip()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise StoreError(f"reference image download failed: HTTP {exc.code}; body={truncate_preview(detail, 500)}") from exc
    except urllib.error.URLError as exc:
        raise StoreError(f"reference image download failed: {exc}") from exc

    normalized_content_type = content_type or mimetypes.guess_type(final_url or normalized_source_url)[0] or "image/png"
    return {
        "source_url": normalized_source_url,
        "content_type": normalized_content_type,
        "filename": _guess_filename_from_url(final_url or normalized_source_url, normalized_content_type),
        "data": data,
    }


def request_openai_image_edit(
    api_key: str,
    base_url: str,
    payload: dict[str, Any],
    reference_images: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calls an OpenAI-compatible image edit API and returns a sanitized response."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise StoreError("openai package is required for the openai image provider") from exc

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=DEFAULT_IMAGE_TIMEOUT_SECONDS,
        max_retries=2,
    )
    image_files = [
        (
            str(item.get("filename", "")).strip() or DEFAULT_REFERENCE_IMAGE_FILENAME,
            bytes(item.get("data", b"")),
            str(item.get("content_type", "")).strip() or "image/png",
        )
        for item in reference_images
    ]
    try:
        result = client.images.edit(
            **payload,
            image=image_files,
            response_format="b64_json",
        )
    except Exception as exc:  # pragma: no cover - provider-specific SDK errors vary by version
        detail = getattr(exc, "message", "") or str(exc)
        raise StoreError(f"openai image edit failed: {truncate_preview(detail, 500)}") from exc

    model_dump = getattr(result, "model_dump", None)
    raw_payload = model_dump(mode="json") if callable(model_dump) else {}
    data_items = raw_payload.get("data", []) if isinstance(raw_payload, dict) else []
    sanitized_items: list[dict[str, Any]] = []
    for item in data_items:
        if not isinstance(item, dict):
            continue
        entry: dict[str, Any] = {}
        url = str(item.get("url", "")).strip()
        if url:
            entry["url"] = url
        mime_type = str(item.get("mime_type", "")).strip()
        if mime_type:
            entry["mime_type"] = mime_type
        if str(item.get("b64_json", "")).strip():
            entry["has_b64_json"] = True
        sanitized_items.append(entry)

    return {
        "created": raw_payload.get("created") if isinstance(raw_payload, dict) else None,
        "data": sanitized_items,
        "_sdk_result": result,
    }


def request_image_with_provider(context: dict[str, Any], provider: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Dispatches the image request to the selected provider."""
    if provider == "ark":
        return request_ark_image(api_key, payload)
    if provider == "openai":
        return request_openai_image(api_key, resolve_image_base_url(context, provider), payload)
    raise StoreError(f"unsupported image provider: {provider}")


def extract_generated_sources(response: dict[str, Any], provider: str) -> list[dict[str, Any]]:
    """Extracts uploadable image sources from a provider response."""
    if provider == "ark":
        sources: list[dict[str, Any]] = []
        for item in response.get("data", []):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "")).strip()
            if url:
                sources.append({"kind": "url", "source_url": url})
        return sources

    if provider == "openai":
        sdk_result = response.get("_sdk_result")
        data_items = getattr(sdk_result, "data", []) if sdk_result is not None else []
        sources = []
        for item in data_items:
            item_url = str(getattr(item, "url", "") or "").strip()
            if item_url:
                sources.append({"kind": "url", "source_url": item_url})
                continue

            b64_json = str(getattr(item, "b64_json", "") or "").strip()
            if not b64_json:
                continue
            try:
                image_bytes = base64.b64decode(b64_json)
            except (ValueError, TypeError) as exc:
                raise StoreError(f"failed to decode openai image bytes: {exc}") from exc
            mime_type = str(getattr(item, "mime_type", "") or "").strip() or "image/png"
            sources.append(
                {
                    "kind": "bytes",
                    "data": image_bytes,
                    "content_type": mime_type,
                }
            )
        return sources

    raise StoreError(f"unsupported image provider: {provider}")


def build_generated_image_object_key(batch_id: str, index: int, prompt: str, variant_index: int = 0) -> str:
    """Builds the object key for generated image uploads."""
    normalized_batch_id = str(batch_id).strip() or "manual"
    prompt_hash = hashlib.sha1(prompt.strip().encode("utf-8")).hexdigest()[:12]
    role = "cover" if index == 0 else f"image-{index:02d}"
    return f"generated-images/{normalized_batch_id}/{index:02d}-{role}-{variant_index:02d}-{prompt_hash}"


def upload_generated_images_to_s3(
    context: dict[str, Any],
    prompts: list[str],
    sources_by_prompt: list[list[dict[str, Any]]],
) -> dict[str, Any]:
    """Uploads generated images to object storage."""
    root = Path(str(context["root"])).resolve()
    tenant_config = context.get("tenant_config")
    uploader = build_s3_uploader(root, tenant_config)
    batch_id = str(context.get("batch_id", "")).strip()

    uploaded_urls_by_prompt: list[list[str]] = []
    uploaded_results: list[dict[str, Any]] = []
    for index, (prompt, generated_sources) in enumerate(zip(prompts, sources_by_prompt, strict=False)):
        prompt_uploaded_urls: list[str] = []
        uploaded_objects: list[dict[str, Any]] = []
        for variant_index, generated_source in enumerate(generated_sources):
            object_key = build_generated_image_object_key(batch_id, index, prompt, variant_index)
            source_kind = str(generated_source.get("kind", "")).strip()
            if source_kind == "bytes":
                uploaded = uploader.upload_bytes(
                    bytes(generated_source.get("data", b"")),
                    object_key,
                    content_type=str(generated_source.get("content_type", "")).strip() or "image/png",
                )
                source_url = ""
            else:
                source_url = str(generated_source.get("source_url", "")).strip()
                uploaded = uploader.upload_from_url(source_url, object_key)

            prompt_uploaded_urls.append(uploaded.url)
            uploaded_objects.append(
                {
                    "bucket": uploaded.bucket,
                    "key": uploaded.key,
                    "url": uploaded.url,
                    "etag": uploaded.etag,
                    "content_type": uploaded.content_type,
                    "size": uploaded.size,
                    "source_url": source_url,
                    "source_kind": source_kind or "url",
                }
            )
        uploaded_urls_by_prompt.append(prompt_uploaded_urls)
        uploaded_results.append(
            {
                "prompt": prompt,
                "source_urls": [
                    str(item.get("source_url", "")).strip()
                    for item in generated_sources
                    if str(item.get("source_url", "")).strip()
                ],
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


def _serialize_sources_for_artifact(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for source in sources:
        source_kind = str(source.get("kind", "")).strip() or "url"
        entry = {"kind": source_kind}
        source_url = str(source.get("source_url", "")).strip()
        if source_url:
            entry["source_url"] = source_url
        if source_kind == "bytes":
            entry["content_type"] = str(source.get("content_type", "")).strip() or "image/png"
            entry["size"] = len(bytes(source.get("data", b"")))
        serialized.append(entry)
    return serialized


def generate_images(
    context: dict[str, Any],
    prompts: list[str],
    *,
    reference_image_urls: list[str] | None = None,
) -> dict[str, Any]:
    """Generates images with the selected provider and uploads them."""
    provider = resolve_image_provider(context)
    api_key = resolve_image_api_key(context, provider)
    normalized_reference_urls: list[str] = []
    seen_reference_urls: set[str] = set()
    for item in reference_image_urls or []:
        value = str(item).strip()
        if not value or value in seen_reference_urls:
            continue
        seen_reference_urls.add(value)
        normalized_reference_urls.append(value)
    reference_images = (
        [download_reference_image(source_url) for source_url in normalized_reference_urls]
        if provider == "openai" and normalized_reference_urls
        else []
    )

    raw_results: list[dict[str, Any]] = []
    sources_by_prompt: list[list[dict[str, Any]]] = []
    for prompt in prompts:
        payload = build_image_payload(context, prompt, provider)
        if provider == "openai" and reference_images:
            response = request_openai_image_edit(
                api_key,
                resolve_image_base_url(context, provider),
                payload,
                reference_images,
            )
        else:
            response = request_image_with_provider(context, provider, api_key, payload)
        generated_sources = extract_generated_sources(response, provider)
        if not generated_sources:
            raise StoreError("image provider did not return any image result")
        sources_by_prompt.append(generated_sources)
        raw_result = {
            "provider": provider,
            "prompt": prompt,
            "response": {key: value for key, value in response.items() if key != "_sdk_result"},
            "sources": _serialize_sources_for_artifact(generated_sources),
            "urls": [str(item.get("source_url", "")).strip() for item in generated_sources if str(item.get("source_url", "")).strip()],
        }
        if reference_images:
            raw_result["reference_images"] = [
                {
                    "source_url": str(item.get("source_url", "")).strip(),
                    "filename": str(item.get("filename", "")).strip(),
                    "content_type": str(item.get("content_type", "")).strip(),
                    "size": len(bytes(item.get("data", b""))),
                }
                for item in reference_images
            ]
        raw_results.append(raw_result)

    uploaded_payload = upload_generated_images_to_s3(context, prompts, sources_by_prompt)
    return {
        "cover_url": uploaded_payload["cover_url"],
        "image_urls": uploaded_payload["image_urls"],
        "raw_results": raw_results,
        "uploaded_results": uploaded_payload["uploaded_results"],
    }


def edit_image(context: dict[str, Any], prompt: str, reference_image_urls: list[str]) -> dict[str, Any]:
    """Edits an image with OpenAI-compatible image editing and uploads the result."""
    provider = resolve_image_provider(context)
    if provider != "openai":
        raise StoreError(f"image editing is not supported for provider: {provider}")

    normalized_reference_urls: list[str] = []
    seen: set[str] = set()
    for item in reference_image_urls:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized_reference_urls.append(value)
    if not normalized_reference_urls:
        raise StoreError("image editing requires at least one reference image")

    api_key = resolve_image_api_key(context, provider)
    payload = build_image_payload(context, prompt, provider)
    reference_images = [download_reference_image(source_url) for source_url in normalized_reference_urls]
    response = request_openai_image_edit(
        api_key,
        resolve_image_base_url(context, provider),
        payload,
        reference_images,
    )
    generated_sources = extract_generated_sources(response, provider)
    if not generated_sources:
        raise StoreError("image provider did not return any image result")

    uploaded_payload = upload_generated_images_to_s3(context, [prompt], [generated_sources])
    return {
        "cover_url": uploaded_payload["cover_url"],
        "image_urls": uploaded_payload["image_urls"],
        "raw_results": [
            {
                "provider": provider,
                "prompt": prompt,
                "response": {key: value for key, value in response.items() if key != "_sdk_result"},
                "reference_images": [
                    {
                        "source_url": str(item.get("source_url", "")).strip(),
                        "filename": str(item.get("filename", "")).strip(),
                        "content_type": str(item.get("content_type", "")).strip(),
                        "size": len(bytes(item.get("data", b""))),
                    }
                    for item in reference_images
                ],
                "sources": _serialize_sources_for_artifact(generated_sources),
                "urls": [str(item.get("source_url", "")).strip() for item in generated_sources if str(item.get("source_url", "")).strip()],
            }
        ],
        "uploaded_results": uploaded_payload["uploaded_results"],
    }


__all__ = [
    "build_generated_image_object_key",
    "build_image_payload",
    "download_reference_image",
    "edit_image",
    "extract_generated_sources",
    "generate_images",
    "request_ark_image",
    "request_image_with_provider",
    "request_openai_image_edit",
    "request_openai_image",
    "resolve_image_api_key",
    "resolve_image_base_url",
    "resolve_image_model",
    "resolve_image_provider",
    "upload_generated_images_to_s3",
]
