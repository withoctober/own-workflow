from __future__ import annotations

import json
import time
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from workflow.core.ai import tenant_api_value
from workflow.core.env import env_value
from workflow.runtime.tenant import TenantRuntimeConfig
from workflow.store import StoreError


COPY_FIELDS = ["title", "content", "tags"]
WORK_FIELDS = [
    "生成日期",
    "标题",
    "正文",
    "标签",
    "封面提示词",
    "封面链接",
    "配图提示词",
    "配图链接",
    "报错信息",
]
TIKHUB_NOTE_ENDPOINT = "https://api.tikhub.io/api/v1/xiaohongshu/web/get_note_info_v4"
TIKHUB_USER_NOTES_ENDPOINT = "https://api.tikhub.io/api/v1/xiaohongshu/app/get_user_notes"
HTML_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)
TIKHUB_API_USER_AGENT = "OpenClaw-ContentCreate/1.0"
ARK_IMAGE_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
DEFAULT_IMAGE_MODEL = "doubao-seedream-5-0-260128"
DEFAULT_IMAGE_SIZE = "1728x2304"
TZ_NAME = "Asia/Shanghai"


def first_non_empty(records: list[dict[str, Any]], *fields: str) -> dict[str, Any]:
    for record in records:
        if any(str(record.get(field, "")).strip() for field in fields):
            return record
    return records[0] if records else {}


def latest_by_date(records: list[dict[str, Any]], date_field: str = "日期") -> dict[str, Any]:
    available = [record for record in records if str(record.get(date_field, "")).strip()]
    if available:
        return sorted(available, key=lambda item: str(item.get(date_field, "")), reverse=True)[0]
    return first_non_empty(records, "今日选题", "正文", "标题")


def select_source_post(records: list[dict[str, Any]], source_url: str = "") -> dict[str, Any]:
    source_url = source_url.strip()
    if source_url:
        for record in records:
            if str(record.get("笔记链接", "")).strip() == source_url:
                return record
    return first_non_empty(records, "标题", "正文", "笔记链接")


def parse_json_or_fallback(text: str) -> Any:
    stripped = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.S)
    if fenced:
        stripped = fenced.group(1).strip()
    return json.loads(stripped)


def parse_copy_payload(text: str) -> dict[str, Any]:
    try:
        payload = parse_json_or_fallback(text)
    except json.JSONDecodeError:
        payload = parse_legacy_copy_text(text)
    if isinstance(payload, dict) and isinstance(payload.get("copy"), dict):
        payload = payload["copy"]
    if not isinstance(payload, dict):
        raise ValueError("文案输出不是 JSON object")
    normalized = normalize_copy_payload(payload)
    title = normalized["title"]
    content = normalized["content"]
    tags_value = normalized["tags"]
    if not title or not content:
        raise ValueError("文案输出缺少 title/content")
    return {"title": title, "content": content, "tags": tags_value}


def parse_legacy_copy_text(text: str) -> dict[str, str]:
    title = ""
    content = ""
    title_match = re.search(r"(?:title|标题)\s*[:：]\s*(.+)", text, re.I)
    if title_match:
        title = title_match.group(1).strip()
    content_match = re.search(r"(?:content|正文(?:内容)?)\s*[:：]\s*(.+)", text, re.I | re.S)
    if content_match:
        content = content_match.group(1).strip()
    return {"title": title, "content": content, "tags": extract_tags(content)}


def parse_image_prompt_payload(text: str) -> dict[str, Any]:
    try:
        payload = parse_json_or_fallback(text)
    except json.JSONDecodeError:
        payload = parse_legacy_prompt_text(text)
    if isinstance(payload, dict) and isinstance(payload.get("image_prompts"), dict):
        payload = payload["image_prompts"]
    if not isinstance(payload, dict):
        raise ValueError("配图提示词输出不是 JSON object")
    normalized = normalize_image_prompt_payload(payload)
    cover_prompt = normalized["cover_prompt"]
    image_prompts = normalized["image_prompts"]
    if not cover_prompt:
        raise ValueError("配图提示词输出缺少 cover_prompt")
    return {"cover_prompt": cover_prompt, "image_prompts": image_prompts}


def parse_legacy_prompt_text(text: str) -> dict[str, Any]:
    chunks = [
        chunk.strip()
        for chunk in re.split(r"\n(?=(?:第[一二三四五六七八九十\\d]+张|【二创配图提示词】|\\d+[.、]))", text)
        if chunk.strip()
    ]
    if not chunks:
        chunks = [text.strip()] if text.strip() else []
    return {"cover_prompt": chunks[0] if chunks else "", "image_prompts": chunks[1:]}


def first_text_value(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def extract_tags(text: str) -> str:
    return " ".join(re.findall(r"#[^\s#]+", text))


def normalize_tag_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip())
    return ""


def normalize_prompt_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"\n(?=第|【|\\d+[.、])", value) if part.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def normalize_copy_payload(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "title": first_text_value(payload.get("title"), payload.get("标题")),
        "content": first_text_value(payload.get("content"), payload.get("正文"), payload.get("正文内容")),
        "tags": normalize_tag_text(payload.get("tags") or payload.get("标签") or ""),
    }


def normalize_image_prompt_payload(payload: dict[str, Any]) -> dict[str, Any]:
    cover_prompt = first_text_value(payload.get("cover_prompt"), payload.get("封面提示词"))
    image_prompts = normalize_prompt_list(payload.get("image_prompts") or payload.get("配图提示词") or [])
    if not cover_prompt and image_prompts:
        cover_prompt = image_prompts[0]
        image_prompts = image_prompts[1:]
    return {"cover_prompt": cover_prompt, "image_prompts": image_prompts}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def nested_get(data: dict[str, Any], *path: str) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def to_datetime_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, ZoneInfo(TZ_NAME)).strftime("%Y-%m-%d %H:%M:%S")
    return str(value).strip()


def truncate_preview(text: str, max_chars: int = 300) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def request_text(url: str, *, timeout: int = 30) -> tuple[str, str]:
    request_obj = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": HTML_USER_AGENT,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request_obj, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.geturl(), body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        detail = f"HTTP {exc.code}"
        if body:
            detail = f"{detail}; body={truncate_preview(body, 500)}"
        raise StoreError(f"主页链接访问失败: {detail}") from exc
    except urllib.error.URLError as exc:
        raise StoreError(f"主页链接访问失败: {exc}") from exc


def profile_url_pattern(pattern: str) -> re.Pattern[str]:
    escaped = re.escape(pattern).replace(re.escape("{user_id}"), r"(?P<user_id>[^/?#]+)")
    return re.compile(escaped)


def extract_profile_user_id(final_url: str, html: str = "", *, pattern: str = "/user/profile/{user_id}") -> str:
    regex = profile_url_pattern(pattern)
    candidates = [final_url, urllib.parse.unquote(final_url), html]
    for candidate in candidates:
        matcher = regex.search(candidate)
        if matcher:
            return str(matcher.group("user_id")).strip()

    query = urllib.parse.parse_qs(urllib.parse.urlsplit(final_url).query)
    for values in query.values():
        for value in values:
            decoded_value = urllib.parse.unquote(value)
            matcher = regex.search(decoded_value)
            if matcher:
                return str(matcher.group("user_id")).strip()
    return ""


def resolve_profile_user_id(source_url: str, *, pattern: str = "/user/profile/{user_id}", timeout: int = 30) -> dict[str, Any]:
    final_url, html = request_text(source_url, timeout=timeout)
    user_id = extract_profile_user_id(final_url, html, pattern=pattern)
    return {
        "source_url": source_url.strip(),
        "final_url": final_url,
        "user_id": user_id,
    }


def extract_note_id(source_url: str) -> str:
    if not source_url.strip():
        return ""
    parsed = urllib.parse.urlsplit(source_url)
    path = urllib.parse.unquote(parsed.path)
    match = re.search(r"/(?:explore|discovery/item)/([^/?#]+)", path)
    if match:
        return match.group(1).strip()
    query = urllib.parse.parse_qs(parsed.query)
    return first_text_value(*(values[0] for key, values in query.items() if key in {"note_id", "id"} and values))


def request_tikhub_json(
    endpoint: str,
    api_key: str,
    params: dict[str, str],
    *,
    timeout: int = 60,
    keep_empty_keys: set[str] | None = None,
    max_retries: int = 2,
    retry_delay_seconds: float = 1.0,
) -> dict[str, Any]:
    keep_empty_keys = keep_empty_keys or set()
    query = urllib.parse.urlencode(
        {
            key: value
            for key, value in params.items()
            if str(value).strip() or key in keep_empty_keys
        }
    )
    separator = "&" if "?" in endpoint else "?"
    url = f"{endpoint}{separator}{query}" if query else endpoint
    request_obj = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": TIKHUB_API_USER_AGENT,
        },
        method="GET",
    )
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(request_obj, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            detail = f"HTTP {exc.code}"
            if body:
                detail = f"{detail}; body={truncate_preview(body, 500)}"
            last_error = StoreError(f"Tikhub 接口调用失败: {detail}")
            should_retry = exc.code in {400, 408, 409, 425, 429, 500, 502, 503, 504}
            if not should_retry or attempt >= max_retries:
                raise last_error from exc
            time.sleep(retry_delay_seconds * (attempt + 1))
        except urllib.error.URLError as exc:
            last_error = StoreError(f"Tikhub 接口请求失败: {exc}")
            if attempt >= max_retries:
                raise last_error from exc
            time.sleep(retry_delay_seconds * (attempt + 1))
    else:
        if last_error is not None:
            raise last_error
        raise StoreError("Tikhub 接口请求失败: 未知错误")
    if not isinstance(payload, dict):
        raise StoreError("Tikhub 接口返回不是 JSON object")
    return payload


def extract_tikhub_note(payload: dict[str, Any]) -> dict[str, Any]:
    outer_data = as_dict(payload.get("data"))
    for item in as_list(outer_data.get("data")):
        record = as_dict(item)
        for note in as_list(record.get("note_list")):
            if isinstance(note, dict):
                return note
        if any(record.get(key) for key in ("title", "desc", "id", "note_id")):
            return record
    return {}


def extract_note_images(note: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    image_candidates = [
        note.get("images_list"),
        note.get("image_list"),
        note.get("images"),
        nested_get(note, "note_card", "image_list"),
    ]
    for candidate in image_candidates:
        for item in as_list(candidate):
            if isinstance(item, str) and item.strip():
                urls.append(item.strip())
                continue
            image = as_dict(item)
            for key in ("original", "url", "url_default", "url_pre", "image_url"):
                value = image.get(key)
                if isinstance(value, str) and value.strip():
                    urls.append(value.strip())
                    break
            for level in as_dict(image.get("url_multi_level")).values():
                if isinstance(level, str) and level.strip():
                    urls.append(level.strip())
            for info in as_list(image.get("info_list")):
                url = first_text_value(as_dict(info).get("url"))
                if url:
                    urls.append(url)
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        deduped.append(url)
    return deduped


def extract_note_topics(note: dict[str, Any], desc: str) -> str:
    values: list[str] = []
    for candidate in (
        note.get("topics"),
        note.get("hash_tag"),
        note.get("tag_list"),
        note.get("tags"),
        nested_get(note, "note_card", "tag_list"),
    ):
        for item in as_list(candidate):
            if isinstance(item, str) and item.strip():
                values.append(item.strip())
                continue
            tag = as_dict(item)
            name = first_text_value(tag.get("name"), tag.get("tag_name"))
            if name:
                values.append(name)
    if not values and desc:
        values = re.findall(r"#([^\s#\[]+)", desc)
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized if normalized.startswith("#") else f"#{normalized}")
    return " ".join(ordered)


def extract_note_link(note: dict[str, Any], source_url: str = "") -> str:
    direct = first_text_value(
        note.get("note_url"),
        note.get("share_url"),
        nested_get(note, "share_info", "link"),
        nested_get(note, "qq_mini_program_info", "webpage_url"),
        nested_get(note, "mini_program_info", "webpage_url"),
    )
    if direct:
        return direct
    note_id = first_text_value(note.get("note_id"), note.get("id"))
    if note_id:
        return f"https://www.xiaohongshu.com/explore/{note_id}"
    return source_url.strip()


def normalize_source_post(note: dict[str, Any], source_url: str) -> dict[str, Any]:
    user = as_dict(note.get("user"))
    title = first_text_value(note.get("title"), nested_get(note, "share_info", "title"))
    content = first_text_value(
        note.get("desc"),
        note.get("content"),
        note.get("description"),
        nested_get(note, "share_info", "content"),
    )
    image_urls = extract_note_images(note)
    cover_url = first_text_value(
        note.get("image"),
        nested_get(note, "share_info", "image"),
        image_urls[0] if image_urls else "",
    )
    note_url = extract_note_link(note, source_url)
    published_raw = note.get("time") or note.get("publish_time") or note.get("last_update_time")
    return {
        "source_url": source_url.strip(),
        "note_url": note_url,
        "note_id": first_text_value(note.get("note_id"), note.get("id")),
        "note_type": first_text_value(note.get("type"), note.get("note_type"), note.get("model_type")),
        "author_name": first_text_value(user.get("nickname"), user.get("name")),
        "author_id": first_text_value(user.get("id"), user.get("userid")),
        "title": title,
        "content": content,
        "tags": extract_note_topics(note, content),
        "cover_url": cover_url,
        "image_urls": image_urls,
        "image_count": len(image_urls),
        "published_at": to_datetime_text(published_raw),
        "published_at_raw": first_text_value(published_raw),
        "like_count": note.get("liked_count", ""),
        "favorite_count": note.get("collected_count", ""),
        "comment_count": note.get("comments_count", ""),
        "share_count": note.get("shared_count", ""),
        "source": "tikhub.get_note_info_v4",
    }


def extract_source_post_image_urls(source_post: dict[str, Any]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()

    def append_url(value: Any) -> None:
        text = str(value).strip()
        if not text or text in seen:
            return
        seen.add(text)
        ordered.append(text)

    append_url(source_post.get("cover_url"))
    for item in as_list(source_post.get("image_urls")):
        append_url(item)
    return ordered


def build_rewrite_prompt_targets(image_urls: list[str]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for index, image_url in enumerate(image_urls, start=1):
        normalized = str(image_url).strip()
        if not normalized:
            continue
        is_cover = index == 1
        role_name = "封面图" if is_cover else f"内页图{index - 1}"
        targets.append(
            {
                "artifact_suffix": f"{index:02d}_{'cover' if is_cover else f'image_{index - 1}'}",
                "role_name": role_name,
                "target_key": "cover_prompt" if is_cover else "image_prompts",
                "image_url": normalized,
            }
        )
    return targets


def fetch_source_post_from_tikhub(
    root: Path,
    source_url: str,
    *,
    endpoint: str = TIKHUB_NOTE_ENDPOINT,
    api_key_env: str = "TIKHUB_API_KEY",
    timeout: int = 60,
    tenant_config: TenantRuntimeConfig | None = None,
) -> dict[str, Any]:
    source_url = source_url.strip()
    if not source_url:
        raise StoreError("缺少 source_url，无法调用 Tikhub 抓取笔记")
    if tenant_config is not None and tenant_config.api_mode == "custom":
        api_key = tenant_api_value(tenant_config, api_key_env)
    else:
        api_key = env_value(api_key_env, root)
    if not api_key:
        raise StoreError(f"缺少 {api_key_env}，无法调用 Tikhub")
    note_id = extract_note_id(source_url)
    response = request_tikhub_json(
        endpoint,
        api_key,
        {
            "note_id": note_id,
            "share_text": source_url,
        },
        timeout=timeout,
    )
    note = extract_tikhub_note(response)
    if not note:
        raise StoreError("Tikhub 已返回响应，但未解析到笔记详情")
    return {
        "request": {
            "endpoint": endpoint,
            "api_key_env": api_key_env,
            "source_url": source_url,
            "note_id": note_id,
            "timeout": timeout,
        },
        "response": response,
        "source_post": normalize_source_post(note, source_url),
    }


def extract_tikhub_notes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    outer_data = as_dict(payload.get("data"))
    for item in as_list(outer_data.get("data")):
        record = as_dict(item)
        note_list = as_list(record.get("note_list"))
        if note_list:
            notes.extend(as_dict(note) for note in note_list if isinstance(note, dict))
            continue
        if any(record.get(key) for key in ("title", "desc", "id", "note_id")):
            notes.append(record)
    return notes


def extract_tikhub_user_notes_page(payload: dict[str, Any]) -> dict[str, Any]:
    outer_code = payload.get("code")
    if outer_code not in (200, "200", None):
        raise StoreError(f"Tikhub 用户笔记接口异常: outer_code={outer_code}")

    outer_data = as_dict(payload.get("data"))
    inner_code = outer_data.get("code")
    inner_message = first_text_value(outer_data.get("message"), payload.get("message"))
    if inner_code not in (0, "0", None):
        raise StoreError(f"Tikhub 用户笔记接口异常: inner_code={inner_code}; message={inner_message}")

    data = as_dict(outer_data.get("data"))
    notes = [note for note in as_list(data.get("notes")) if isinstance(note, dict)]
    return {
        "notes": notes,
        "has_more": bool(data.get("has_more")),
        "last_cursor": first_text_value(data.get("cursor"), data.get("lastCursor")),
    }


def fetch_user_notes_from_tikhub(
    root: Path,
    *,
    user_id: str,
    last_cursor: str = "",
    endpoint: str = TIKHUB_USER_NOTES_ENDPOINT,
    api_key_env: str = "TIKHUB_API_KEY",
    timeout: int = 60,
    tenant_config: TenantRuntimeConfig | None = None,
) -> dict[str, Any]:
    if tenant_config is not None and tenant_config.api_mode == "custom":
        api_key = tenant_api_value(tenant_config, api_key_env)
    else:
        api_key = env_value(api_key_env, root)
    if not api_key:
        raise StoreError(f"缺少 {api_key_env}，无法调用 Tikhub")

    params = {
        "user_id": user_id.strip(),
        "cursor": last_cursor.strip(),
    }
    response = request_tikhub_json(endpoint, api_key, params, timeout=timeout, keep_empty_keys={"cursor"})
    page = extract_tikhub_user_notes_page(response)
    return {
        "request": {
            "endpoint": endpoint,
            "api_key_env": api_key_env,
            "user_id": user_id.strip(),
            "last_cursor": last_cursor.strip(),
            "timeout": timeout,
        },
        "response": response,
        **page,
    }


def build_image_payload(context: dict[str, Any], prompt: str) -> dict[str, Any]:
    step = context.get("step", {})
    return {
        "model": step.get("image_model", DEFAULT_IMAGE_MODEL),
        "prompt": prompt,
        "sequential_image_generation": step.get("sequential_image_generation", "disabled"),
        "response_format": "url",
        "size": step.get("image_size", DEFAULT_IMAGE_SIZE),
        "stream": False,
        "watermark": bool(step.get("watermark", False)),
    }


def request_image(api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
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
        with urllib.request.urlopen(request_obj, timeout=300) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise StoreError(f"图片接口调用失败: HTTP {exc.code}; body={truncate_preview(detail, 500)}") from exc
    except urllib.error.URLError as exc:
        raise StoreError(f"图片接口请求失败: {exc}") from exc
    if not isinstance(result, dict):
        raise StoreError("图片接口返回不是 JSON object")
    return result


def extract_image_urls(response: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for item in as_list(response.get("data")):
        record = as_dict(item)
        url = first_text_value(record.get("url"))
        if url:
            urls.append(url)
    return urls


def generate_images(context: dict[str, Any], prompts: list[str]) -> dict[str, Any]:
    root = Path(str(context["root"])).resolve()
    tenant_config = context.get("tenant_config")
    if tenant_config is not None and tenant_config.api_mode == "custom":
        api_key = tenant_api_value(tenant_config, "ARK_API_KEY")
    else:
        api_key = env_value("ARK_API_KEY", root)
    if not api_key:
        raise StoreError("缺少 ARK_API_KEY，无法执行实际出图")

    raw_results: list[dict[str, Any]] = []
    urls_by_prompt: list[list[str]] = []
    for prompt in prompts:
        response = request_image(api_key, build_image_payload(context, prompt))
        urls = extract_image_urls(response)
        if not urls:
            raise StoreError("图片接口未返回 URL")
        urls_by_prompt.append(urls)
        raw_results.append({"prompt": prompt, "response": response, "urls": urls})

    cover_url = urls_by_prompt[0][0] if urls_by_prompt else ""
    image_urls = [urls[0] for urls in urls_by_prompt[1:] if urls]
    return {"cover_url": cover_url, "image_urls": image_urls, "raw_results": raw_results}


def current_date_text(context: dict[str, Any]) -> str:
    timezone = str(context.get("timezone", TZ_NAME)).strip() or TZ_NAME
    return datetime.now(ZoneInfo(timezone)).strftime("%Y-%m-%d")


def build_work_record(
    context: dict[str, Any],
    copy_payload: dict[str, Any],
    prompt_payload: dict[str, Any],
    image_payload: dict[str, Any],
) -> dict[str, Any]:
    batch_id = str(context.get("batch_id", "")).strip()
    title = str(copy_payload.get("title", "")).strip()
    content = str(copy_payload.get("content", "")).strip()
    tags = str(copy_payload.get("tags", "")).strip() or extract_tags(content)
    image_prompts = [str(item).strip() for item in prompt_payload.get("image_prompts", []) if str(item).strip()]
    return {
        "生成日期": {
            "text": current_date_text(context),
            "link": f"workflow://runs/{batch_id or 'manual'}",
        },
        "标题": title,
        "正文": content,
        "标签": tags,
        "封面提示词": str(prompt_payload.get("cover_prompt", "")).strip(),
        "封面链接": str(image_payload.get("cover_url", "")).strip(),
        "配图提示词": "\n\n".join(image_prompts),
        "配图链接": "\n".join(str(url).strip() for url in image_payload.get("image_urls", []) if str(url).strip()),
        "报错信息": "",
    }


def filter_work_record(target_fields: list[str], record: dict[str, Any]) -> dict[str, Any]:
    available = [field for field in target_fields if field and field != "record_id"]
    if not available:
        available = WORK_FIELDS
    filtered = {key: value for key, value in record.items() if key in available}
    if not filtered:
        expected = "、".join(WORK_FIELDS)
        raise StoreError(f"“生成作品库”表缺少可写字段。至少需要包含以下字段之一：{expected}。")
    return filtered


__all__ = [
    "COPY_FIELDS",
    "WORK_FIELDS",
    "build_rewrite_prompt_targets",
    "build_work_record",
    "extract_source_post_image_urls",
    "fetch_source_post_from_tikhub",
    "filter_work_record",
    "generate_images",
    "latest_by_date",
    "normalize_copy_payload",
    "normalize_image_prompt_payload",
    "parse_copy_payload",
    "parse_image_prompt_payload",
]
