from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, NamedTuple

from workflow.billing import record_usage_event
from workflow.core.ai import tenant_api_value
from workflow.core.env import env_value
from workflow.integrations import build_s3_uploader
from workflow.store import StoreError


OPENAI_IMAGE_BASE_URL_ENV = "OPENAI_IMAGE_BASE_URL"
OPENAI_IMAGE_MODEL_ENV = "OPENAI_IMAGE_MODEL"
DEFAULT_OPENAI_IMAGE_MODEL = "gpt-image-2"
DEFAULT_IMAGE_SIZE = "1728x2304"
DEFAULT_IMAGE_TIMEOUT_SECONDS = 600
DEFAULT_REFERENCE_IMAGE_FILENAME = "reference-image.png"
OPENAI_IMAGE_USER_AGENT = "cc-switch/1.0"


class ImageProviderConfig(NamedTuple):
    provider: str
    base_url: str
    api_key: str
    model: str


def truncate_preview(text: str, max_chars: int = 300) -> str:
    """Returns a shortened preview for remote error bodies."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _step_value(context: dict[str, Any], key: str) -> str:
    step = context.get("step", {})
    return str(step.get(key, "")).strip()


def _normalize_reference_image_urls(reference_image_urls: list[str] | None) -> list[str]:
    normalized_urls: list[str] = []
    seen_urls: set[str] = set()
    for item in reference_image_urls or []:
        value = str(item).strip()
        if not value or value in seen_urls:
            continue
        seen_urls.add(value)
        normalized_urls.append(value)
    return normalized_urls


def _reference_image_artifacts(
    reference_images: list[dict[str, Any]],
    reference_image_urls: list[str],
) -> list[dict[str, Any]]:
    if reference_images:
        return [
            {
                "source_url": str(item.get("source_url", "")).strip(),
                "filename": str(item.get("filename", "")).strip(),
                "content_type": str(item.get("content_type", "")).strip(),
                "size": len(bytes(item.get("data", b""))),
            }
            for item in reference_images
        ]
    return [{"source_url": source_url} for source_url in reference_image_urls]


def _tenant_value(
    context: dict[str, Any],
    keys: tuple[str, ...],
) -> str:
    tenant_config = context.get("tenant_config")
    run_overrides = {}
    if tenant_config is not None:
        payload = getattr(tenant_config, "payload", {})
        run_overrides = payload.get("run_overrides") if isinstance(payload, dict) else {}
    if isinstance(run_overrides, dict):
        for key in keys:
            value = run_overrides.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()

    if tenant_config is not None and getattr(tenant_config, "api_mode", "") == "custom":
        for key in keys:
            value = tenant_api_value(tenant_config, key)
            if value:
                return value

    return ""


def _system_value(
    context: dict[str, Any],
    keys: tuple[str, ...],
) -> str:
    root = Path(str(context.get("root") or "")).resolve()
    for key in keys:
        value = env_value(key, root)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def resolve_image_config(context: dict[str, Any]) -> ImageProviderConfig:
    """Resolves the required image provider settings from runtime context."""
    base_url = _tenant_value(
        context,
        (OPENAI_IMAGE_BASE_URL_ENV,),
    ) or _system_value(
        context,
        (OPENAI_IMAGE_BASE_URL_ENV,),
    )
    if not base_url:
        raise StoreError(f"missing {OPENAI_IMAGE_BASE_URL_ENV} for image generation")
    api_key = _tenant_value(context, ("OPENAI_API_KEY",))
    if not api_key:
        raise StoreError("当前空间未配置图文生成 OPENAI_API_KEY")
    model = _tenant_value(
        context,
        (OPENAI_IMAGE_MODEL_ENV,),
    ) or DEFAULT_OPENAI_IMAGE_MODEL
    return ImageProviderConfig(provider="openai", base_url=base_url, api_key=api_key, model=model)


def build_image_payload(
    context: dict[str, Any],
    prompt: str,
    config: ImageProviderConfig,
    reference_image_urls: list[str] | None = None,
) -> dict[str, Any]:
    """Builds the provider-specific image request payload."""
    payload: dict[str, Any] = {
        "model": config.model,
        "prompt": prompt,
    }
    size = _step_value(context, "image_size")
    if size:
        payload["size"] = size
    return payload


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
        default_headers={"User-Agent": OPENAI_IMAGE_USER_AGENT},
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
    """Calls RightCode's image generation endpoint with reference images."""
    normalized_base_url = str(base_url or "").rstrip("/")
    request_payload = dict(payload)
    request_payload["image"] = [
        str(item.get("source_url", "")).strip()
        for item in reference_images
        if str(item.get("source_url", "")).strip()
    ]
    request_payload["response_format"] = str(request_payload.get("response_format") or "url").strip() or "url"
    request_url = f"{normalized_base_url}/images/generations"
    request_body = json.dumps(request_payload).encode("utf-8")
    request_obj = urllib.request.Request(
        request_url,
        data=request_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": OPENAI_IMAGE_USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request_obj, timeout=DEFAULT_IMAGE_TIMEOUT_SECONDS) as response:
            raw_bytes = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise StoreError(f"rightcode image edit failed: HTTP {exc.code}; body={truncate_preview(detail, 500)}") from exc
    except urllib.error.URLError as exc:
        raise StoreError(f"rightcode image edit failed: {exc}") from exc

    try:
        raw_payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StoreError(f"rightcode image edit returned invalid JSON: {exc}") from exc

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
        "_raw_data": data_items,
    }


def request_image_with_provider(config: ImageProviderConfig, payload: dict[str, Any]) -> dict[str, Any]:
    """Dispatches the image request to the selected provider."""
    if config.provider != "openai":
        raise StoreError(f"unsupported image provider: {config.provider}")
    return request_openai_image(config.api_key, config.base_url, payload)


def extract_generated_sources(response: dict[str, Any], provider: str) -> list[dict[str, Any]]:
    """Extracts uploadable image sources from a provider response."""
    if provider != "openai":
        raise StoreError(f"unsupported image provider: {provider}")

    raw_data_items = response.get("_raw_data")
    if isinstance(raw_data_items, list):
        sources = []
        for item in raw_data_items:
            if not isinstance(item, dict):
                continue
            item_url = str(item.get("url", "") or "").strip()
            if item_url:
                sources.append({"kind": "url", "source_url": item_url})
                continue
            b64_json = str(item.get("b64_json", "") or "").strip()
            if not b64_json:
                continue
            try:
                data = base64.b64decode(b64_json)
            except (ValueError, TypeError) as exc:
                raise StoreError(f"generated image data decode failed: {exc}") from exc
            mime_type = str(item.get("mime_type", "") or "").strip() or "image/png"
            sources.append({"kind": "bytes", "data": data, "mime_type": mime_type})
        if sources:
            return sources

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
    billing_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generates images with the selected provider and uploads them."""
    normalized_prompts: list[str] = []
    for index, prompt in enumerate(prompts):
        normalized_prompt = str(prompt).strip()
        if not normalized_prompt:
            raise StoreError(f"image generation prompt at index {index} is empty")
        normalized_prompts.append(normalized_prompt)
    if not normalized_prompts:
        raise StoreError("image generation prompt is empty")

    config = resolve_image_config(context)
    normalized_reference_urls = _normalize_reference_image_urls(reference_image_urls)
    reference_images = (
        [download_reference_image(source_url) for source_url in normalized_reference_urls]
        if normalized_reference_urls
        else []
    )

    raw_results: list[dict[str, Any]] = []
    sources_by_prompt: list[list[dict[str, Any]]] = []
    for index, prompt in enumerate(normalized_prompts):
        payload = build_image_payload(
            context,
            prompt,
            config,
            None,
        )
        if reference_images:
            response = request_openai_image_edit(
                config.api_key,
                config.base_url,
                payload,
                reference_images,
            )
        else:
            response = request_image_with_provider(config, payload)
        generated_sources = extract_generated_sources(response, config.provider)
        if not generated_sources:
            raise StoreError("image provider did not return any image result")
        if isinstance(billing_context, dict):
            request_id = str(billing_context.get("request_id") or "").strip()
            provider_event_id = str(billing_context.get("provider_event_id") or "").strip()
            if request_id:
                request_id = f"{request_id}:{index}"
            if provider_event_id:
                provider_event_id = f"{provider_event_id}:{index}"
            record_usage_event(
                root=Path(str(context["root"])).resolve(),
                tenant_config=context.get("tenant_config"),
                tenant_id=str(billing_context.get("tenant_id") or "").strip(),
                provider=config.provider,
                channel=str(billing_context.get("channel") or "图片生成").strip(),
                title=str(billing_context.get("title") or "图片生成").strip(),
                detail=str(billing_context.get("detail") or "已记录图片生成").strip(),
                feature_key=str(billing_context.get("feature_key") or "").strip(),
                model_name=config.model,
                request_id=request_id,
                provider_event_id=provider_event_id,
                related_resource_type=str(billing_context.get("related_resource_type") or "").strip(),
                related_resource_id=str(billing_context.get("related_resource_id") or "").strip(),
                image_count=len(generated_sources),
                request_count=1,
                payload={
                    **{key: value for key, value in billing_context.items() if key not in {"tenant_id", "channel", "title", "detail", "feature_key", "request_id", "provider_event_id", "related_resource_type", "related_resource_id"}},
                    "prompt_index": index,
                    "provider_model": config.model,
                    "prompt_preview": prompt[:120],
                    "reference_image_count": len(normalized_reference_urls),
                },
            )
        sources_by_prompt.append(generated_sources)
        raw_result = {
            "provider": config.provider,
            "prompt": prompt,
            "response": {key: value for key, value in response.items() if key != "_sdk_result"},
            "sources": _serialize_sources_for_artifact(generated_sources),
            "urls": [str(item.get("source_url", "")).strip() for item in generated_sources if str(item.get("source_url", "")).strip()],
        }
        if reference_images:
            raw_result["reference_images"] = _reference_image_artifacts(reference_images, normalized_reference_urls)
        raw_results.append(raw_result)

    uploaded_payload = upload_generated_images_to_s3(context, normalized_prompts, sources_by_prompt)
    return {
        "cover_url": uploaded_payload["cover_url"],
        "image_urls": uploaded_payload["image_urls"],
        "raw_results": raw_results,
        "uploaded_results": uploaded_payload["uploaded_results"],
    }


def edit_image(
    context: dict[str, Any],
    prompt: str,
    reference_image_urls: list[str],
    *,
    billing_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Edits an image with a supported image editing provider and uploads the result."""
    config = resolve_image_config(context)
    if config.provider != "openai":
        raise StoreError(f"image editing is not supported for provider: {config.provider}")

    normalized_reference_urls = _normalize_reference_image_urls(reference_image_urls)
    if not normalized_reference_urls:
        raise StoreError("image editing requires at least one reference image")

    payload = build_image_payload(
        context,
        prompt,
        config,
        None,
    )
    reference_images = [download_reference_image(source_url) for source_url in normalized_reference_urls]
    response = request_openai_image_edit(
        config.api_key,
        config.base_url,
        payload,
        reference_images,
    )
    generated_sources = extract_generated_sources(response, config.provider)
    if not generated_sources:
        raise StoreError("image provider did not return any image result")
    if isinstance(billing_context, dict):
        record_usage_event(
            root=Path(str(context["root"])).resolve(),
            tenant_config=context.get("tenant_config"),
            tenant_id=str(billing_context.get("tenant_id") or "").strip(),
            provider=config.provider,
            channel=str(billing_context.get("channel") or "图片生成").strip(),
            title=str(billing_context.get("title") or "图片重绘").strip(),
            detail=str(billing_context.get("detail") or "已记录图片重绘").strip(),
            feature_key=str(billing_context.get("feature_key") or "").strip(),
            model_name=config.model,
            request_id=str(billing_context.get("request_id") or "").strip(),
            provider_event_id=str(billing_context.get("provider_event_id") or "").strip(),
            related_resource_type=str(billing_context.get("related_resource_type") or "").strip(),
            related_resource_id=str(billing_context.get("related_resource_id") or "").strip(),
            image_count=len(generated_sources),
            request_count=1,
            payload={
                **{key: value for key, value in billing_context.items() if key not in {"tenant_id", "channel", "title", "detail", "feature_key", "request_id", "provider_event_id", "related_resource_type", "related_resource_id"}},
                "provider_model": config.model,
                "prompt_preview": prompt[:120],
                "reference_image_count": len(normalized_reference_urls),
            },
        )

    uploaded_payload = upload_generated_images_to_s3(context, [prompt], [generated_sources])
    return {
        "cover_url": uploaded_payload["cover_url"],
        "image_urls": uploaded_payload["image_urls"],
        "raw_results": [
            {
                "provider": config.provider,
                "prompt": prompt,
                "response": {key: value for key, value in response.items() if key != "_sdk_result"},
                "reference_images": _reference_image_artifacts(reference_images, normalized_reference_urls),
                "sources": _serialize_sources_for_artifact(generated_sources),
                "urls": [str(item.get("source_url", "")).strip() for item in generated_sources if str(item.get("source_url", "")).strip()],
            }
        ],
        "uploaded_results": uploaded_payload["uploaded_results"],
    }


__all__ = [
    "ImageProviderConfig",
    "build_generated_image_object_key",
    "build_image_payload",
    "download_reference_image",
    "edit_image",
    "extract_generated_sources",
    "generate_images",
    "request_image_with_provider",
    "request_openai_image_edit",
    "request_openai_image",
    "resolve_image_config",
    "upload_generated_images_to_s3",
]
