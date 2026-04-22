from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from workflow.store.base import StoreError, as_dict, as_list
from workflow.store.feishu import FeishuResourceConfig, FeishuStore


DEFAULT_FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
TABLE_PAGE_SIZE = 100


def build_feishu_config_payload(
    *,
    tables: dict[str, Any],
    docs: dict[str, Any],
    api_base: str = DEFAULT_FEISHU_API_BASE,
    timeout_seconds: int = 30,
    max_retries: int = 2,
    user_id_type: str = "open_id",
) -> dict[str, Any]:
    return {
        "api_base": api_base,
        "timeout_seconds": timeout_seconds,
        "max_retries": max_retries,
        "user_id_type": user_id_type,
        "tables": tables,
        "docs": docs,
    }


def build_feishu_store(
    root: Path,
    *,
    app_id: str,
    app_secret: str,
    tenant_access_token: str | None = None,
    api_base: str = DEFAULT_FEISHU_API_BASE,
    timeout_seconds: int = 30,
    max_retries: int = 2,
    user_id_type: str = "open_id",
) -> FeishuStore:
    return FeishuStore(
        root,
        FeishuResourceConfig(
            path=root / "config" / "_postgres_feishu_runtime.json",
            payload={
                "app_id": app_id,
                "app_secret": app_secret,
                "tenant_access_token": tenant_access_token or "",
                "api_base": api_base,
                "timeout_seconds": timeout_seconds,
                "max_retries": max_retries,
                "user_id_type": user_id_type,
                "tables": {},
                "docs": {},
            },
        ),
    )


def validate_feishu_credentials(
    root: Path,
    *,
    app_id: str,
    app_secret: str,
    tenant_access_token: str | None = None,
    api_base: str = DEFAULT_FEISHU_API_BASE,
    timeout_seconds: int = 30,
    max_retries: int = 2,
) -> None:
    store = build_feishu_store(
        root,
        app_id=app_id,
        app_secret=app_secret,
        tenant_access_token=tenant_access_token,
        api_base=api_base,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
    try:
        store._access_token()
    except StoreError as exc:
        raise StoreError(f"飞书 App ID / App Secret 校验失败: {exc}") from exc


def extract_bitable_app_token(raw_url: str) -> str:
    parsed = urlsplit(raw_url.strip())
    path_parts = [part for part in unquote(parsed.path).split("/") if part]
    query = parse_qs(parsed.query)

    for index, part in enumerate(path_parts):
        if part in {"base", "bitable"} and index + 1 < len(path_parts):
            token = path_parts[index + 1].strip()
            if token:
                return token

    for key in ("app_token", "appToken"):
        values = query.get(key) or []
        if values and values[0].strip():
            return values[0].strip()

    raise StoreError("无法从多维表格地址中解析 app_token，请确认链接形如 https://xxx.feishu.cn/base/<app_token>")


def fetch_bitable_tables(
    root: Path,
    *,
    app_id: str,
    app_secret: str,
    app_token: str,
    tenant_access_token: str | None = None,
    api_base: str = DEFAULT_FEISHU_API_BASE,
    timeout_seconds: int = 30,
    max_retries: int = 2,
) -> list[dict[str, str]]:
    store = build_feishu_store(
        root,
        app_id=app_id,
        app_secret=app_secret,
        tenant_access_token=tenant_access_token,
        api_base=api_base,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
    tables: list[dict[str, str]] = []
    seen_table_ids: set[str] = set()
    page_token: str | None = None

    while True:
        query: dict[str, Any] = {"page_size": TABLE_PAGE_SIZE}
        if page_token:
            query["page_token"] = page_token
        response = store._request_json("GET", f"/bitable/v1/apps/{app_token}/tables", query=query)
        data = as_dict(response.get("data"))
        items = as_list(data.get("items"))
        if not items and not tables:
            raise StoreError(f"多维表格下未返回任何数据表: {app_token}")
        for item in items:
            table = as_dict(item)
            table_id = str(table.get("table_id") or table.get("id") or "").strip()
            name = str(table.get("name") or table.get("table_name") or "").strip()
            if not table_id or not name or table_id in seen_table_ids:
                continue
            seen_table_ids.add(table_id)
            tables.append({"name": name, "table_id": table_id})
        if not data.get("has_more"):
            break
        page_token = str(data.get("page_token") or "").strip() or None
        if not page_token:
            break

    if not tables:
        raise StoreError(f"无法从多维表格中解析 table_id: {app_token}")
    return tables


def sanitize_token(raw: str) -> str:
    return re.split(r"[?#]", raw.strip(), maxsplit=1)[0].strip()


def parse_feishu_document_link(raw_url: str) -> tuple[str, str]:
    parsed = urlsplit(raw_url.strip())
    path_parts = [part for part in unquote(parsed.path).split("/") if part]
    query = parse_qs(parsed.query)

    for index, part in enumerate(path_parts):
        normalized = part.lower()
        if normalized in {"docx", "docs", "doc"} and index + 1 < len(path_parts):
            token = sanitize_token(path_parts[index + 1])
            if token:
                return "docx", token
        if normalized == "wiki" and index + 1 < len(path_parts):
            token = sanitize_token(path_parts[index + 1])
            if token:
                return "wiki", token

    for key in ("document_id", "doc_token", "token"):
        values = query.get(key) or []
        if values and values[0].strip():
            return "docx", sanitize_token(values[0])

    raise StoreError("无法从文档地址中解析 document_id/wiki token，请确认链接形如 https://xxx.feishu.cn/docx/<token> 或 /wiki/<token>")


def resolve_wiki_to_document(store: FeishuStore, wiki_token: str) -> tuple[str, str]:
    response = store._request_json("GET", "/wiki/v2/spaces/get_node", query={"token": wiki_token})
    data = as_dict(response.get("data"))
    node = as_dict(data.get("node"))
    obj_type = str(node.get("obj_type") or data.get("obj_type") or "").strip().lower()
    document_id = str(node.get("obj_token") or data.get("obj_token") or "").strip()
    title = str(node.get("title") or data.get("title") or "").strip()
    if obj_type and obj_type not in {"docx", "docs"}:
        raise StoreError(f"Wiki 链接指向的不是飞书文档，而是 {obj_type}")
    if not document_id:
        raise StoreError("无法从 Wiki 链接解析 document_id")
    return document_id, title


def validate_document_access(store: FeishuStore, document_id: str) -> None:
    store._request_json("GET", f"/docx/v1/documents/{document_id}/raw_content")


def fetch_document_title(store: FeishuStore, document_id: str) -> str:
    try:
        response = store._request_json("GET", f"/docx/v1/documents/{document_id}")
    except StoreError:
        return ""
    data = as_dict(response.get("data"))
    document = as_dict(data.get("document"))
    return str(document.get("title") or data.get("title") or "").strip()


def resolve_document(
    root: Path,
    *,
    app_id: str,
    app_secret: str,
    raw_url: str,
    tenant_access_token: str | None = None,
    api_base: str = DEFAULT_FEISHU_API_BASE,
    timeout_seconds: int = 30,
    max_retries: int = 2,
) -> dict[str, str]:
    store = build_feishu_store(
        root,
        app_id=app_id,
        app_secret=app_secret,
        tenant_access_token=tenant_access_token,
        api_base=api_base,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
    link_type, token = parse_feishu_document_link(raw_url)
    title = ""
    document_id = ""

    if link_type == "docx":
        document_id = token
    elif link_type == "wiki":
        document_id, title = resolve_wiki_to_document(store, token)
    else:
        raise StoreError("仅支持 docx 或 wiki 飞书文档链接")

    validate_document_access(store, document_id)
    if not title:
        title = fetch_document_title(store, document_id) or document_id
    return {"document_id": document_id, "title": title}


def build_remote_feishu_config(
    root: Path,
    *,
    app_id: str,
    app_secret: str,
    tenant_access_token: str | None,
    table_url: str,
    document_urls: dict[str, str],
    timeout_seconds: int = 30,
    max_retries: int = 2,
    api_base: str = DEFAULT_FEISHU_API_BASE,
) -> dict[str, Any]:
    validate_feishu_credentials(
        root,
        app_id=app_id,
        app_secret=app_secret,
        tenant_access_token=tenant_access_token,
        api_base=api_base,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
    app_token = extract_bitable_app_token(table_url)
    tables = fetch_bitable_tables(
        root,
        app_id=app_id,
        app_secret=app_secret,
        app_token=app_token,
        tenant_access_token=tenant_access_token,
        api_base=api_base,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
    docs: dict[str, dict[str, str]] = {}
    for doc_name, document_url in document_urls.items():
        docs[doc_name] = resolve_document(
            root,
            app_id=app_id,
            app_secret=app_secret,
            raw_url=document_url,
            tenant_access_token=tenant_access_token,
            api_base=api_base,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
    return build_feishu_config_payload(
        tables={
            table["name"]: {
                "app_token": app_token,
                "table_id": table["table_id"],
            }
            for table in tables
        },
        docs=docs,
        api_base=api_base,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        user_id_type="open_id",
    )
