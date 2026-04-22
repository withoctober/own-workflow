from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from workflow.core.env import env_value
from workflow.store.base import (
    StoreError,
    as_dict,
    as_list,
    backoff_seconds,
    chunked,
    feishu_doc_uri,
    feishu_table_uri,
    markdown_to_docx_blocks,
    normalize_doc_mode,
    normalize_table_mode,
    parse_json_safely,
)


DEFAULT_FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
RETRYABLE_HTTP_STATUSES = {429, 500, 503, 504}
RETRYABLE_FEISHU_CODES = {99991400, 1254291, 1254607, 1770020, 1770036}
FEISHU_TABLE_RECORD_BATCH_SIZE = 500


@dataclass
class FeishuResourceConfig:
    path: Path
    payload: dict[str, Any]

    @property
    def app_id(self) -> str:
        return str(self.payload.get("app_id", "")).strip()

    @property
    def app_secret(self) -> str:
        return str(self.payload.get("app_secret", "")).strip()

    @property
    def tenant_access_token(self) -> str | None:
        value = self.payload.get("tenant_access_token")
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @property
    def app_id_env(self) -> str:
        return str(self.payload.get("app_id_env", "FEISHU_APP_ID"))

    @property
    def app_secret_env(self) -> str:
        return str(self.payload.get("app_secret_env", "FEISHU_APP_SECRET"))

    @property
    def tenant_access_token_env(self) -> str | None:
        value = self.payload.get("tenant_access_token_env")
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @property
    def api_base(self) -> str:
        return str(self.payload.get("api_base", DEFAULT_FEISHU_API_BASE)).rstrip("/")

    @property
    def timeout_seconds(self) -> int:
        return int(self.payload.get("timeout_seconds", 30))

    @property
    def max_retries(self) -> int:
        return int(self.payload.get("max_retries", 2))

    @property
    def user_id_type(self) -> str:
        return str(self.payload.get("user_id_type", "open_id"))

    @property
    def tables(self) -> dict[str, dict[str, Any]]:
        raw = self.payload.get("tables", {})
        return raw if isinstance(raw, dict) else {}

    @property
    def docs(self) -> dict[str, dict[str, Any]]:
        raw = self.payload.get("docs", {})
        return raw if isinstance(raw, dict) else {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.payload, ensure_ascii=False, indent=2), encoding="utf-8")


class FeishuStore:
    """Feishu bitable and docx store adapter."""

    def __init__(self, root: Path, config: FeishuResourceConfig) -> None:
        self.root = root
        self.config = config
        self._tenant_access_token: str | None = None
        self._token_expires_at = 0.0

    def read_table(self, name: str) -> list[dict[str, Any]]:
        table = self._require_table(name)
        rows: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            query = {"page_size": 500, "user_id_type": self.config.user_id_type}
            if page_token:
                query["page_token"] = page_token
            response = self._request_json(
                "GET",
                f"/bitable/v1/apps/{table['app_token']}/tables/{table['table_id']}/records",
                query=query,
            )
            data = as_dict(response.get("data"))
            for item in as_list(data.get("items")):
                record = as_dict(item)
                fields = as_dict(record.get("fields"))
                if not fields:
                    continue
                enriched = {"record_id": record.get("record_id") or record.get("id")}
                enriched.update(fields)
                rows.append(enriched)
            if not data.get("has_more"):
                break
            page_token = str(data.get("page_token") or "").strip() or None
            if not page_token:
                break
        return rows

    def write_table(self, name: str, records: list[dict[str, Any]], mode: str = "replace") -> str:
        table = self._require_table(name)
        normalized_mode = normalize_table_mode(mode)
        filtered = [record for record in records if isinstance(record, dict)]
        if normalized_mode == "replace":
            self.delete_table(name)
        self._batch_create_table_records(table, filtered)
        return feishu_table_uri(table["app_token"], table["table_id"], name)

    def update_table_records(self, name: str, records: list[dict[str, Any]]) -> str:
        table = self._require_table(name)
        self._batch_update_table_records(table, [record for record in records if isinstance(record, dict)])
        return feishu_table_uri(table["app_token"], table["table_id"], name)

    def list_table_fields(self, name: str) -> list[str]:
        table = self._require_table(name)
        response = self._request_json(
            "GET",
            f"/bitable/v1/apps/{table['app_token']}/tables/{table['table_id']}/fields",
            query={"page_size": 500, "user_id_type": self.config.user_id_type},
        )
        data = as_dict(response.get("data"))
        fields: list[str] = []
        for item in as_list(data.get("items")):
            field = as_dict(item)
            field_name = str(field.get("field_name", "")).strip()
            if field_name and field_name not in fields:
                fields.append(field_name)
        return fields

    def delete_table(self, name: str) -> str:
        table = self._require_table(name)
        record_ids = [str(record.get("record_id", "")).strip() for record in self.read_table(name)]
        self._batch_delete_table_records(table, [record_id for record_id in record_ids if record_id])
        return feishu_table_uri(table["app_token"], table["table_id"], name)

    def read_doc(self, name: str) -> str:
        doc = self._require_doc(name, allow_missing_document_id=True)
        document_id = str(doc.get("document_id", "")).strip()
        if not document_id:
            return ""
        response = self._request_json("GET", f"/docx/v1/documents/{document_id}/raw_content")
        data = as_dict(response.get("data"))
        return str(data.get("content", ""))

    def write_doc(self, name: str, content: str, mode: str = "replace") -> str:
        normalized_mode = normalize_doc_mode(mode)
        if normalized_mode == "append":
            existing = self.read_doc(name)
            content = f"{existing.rstrip()}\n\n{content}".strip() if existing else content

        doc = self._ensure_document(name)
        document_id = str(doc["document_id"])
        self._clear_document_children(document_id)
        self._append_doc_blocks(document_id, markdown_to_docx_blocks(content))
        return feishu_doc_uri(document_id, name)

    def delete_doc(self, name: str) -> str:
        doc = self._require_doc(name, allow_missing_document_id=True)
        document_id = str(doc.get("document_id", "")).strip()
        if document_id:
            self._request_json("DELETE", f"/drive/v1/files/{document_id}", query={"type": "docx"})
        doc["document_id"] = ""
        self.config.save()
        return feishu_doc_uri(document_id or "unknown", name)

    def target_exists(self, name: str) -> bool:
        table = self.config.tables.get(name)
        if isinstance(table, dict):
            return bool(str(table.get("app_token", "")).strip() and str(table.get("table_id", "")).strip())
        doc = self.config.docs.get(name)
        if isinstance(doc, dict):
            if str(doc.get("document_id", "")).strip():
                return True
            title = str(doc.get("title", "")).strip() or name
            folder_token = str(doc.get("folder_token", "")).strip()
            return bool(title or folder_token)
        return False

    def _ensure_document(self, name: str) -> dict[str, Any]:
        doc = self._require_doc(name, allow_missing_document_id=True)
        document_id = str(doc.get("document_id", "")).strip()
        if document_id:
            return doc

        payload: dict[str, Any] = {"title": str(doc.get("title", "")).strip() or name}
        folder_token = str(doc.get("folder_token", "")).strip()
        if folder_token:
            payload["folder_token"] = folder_token

        response = self._request_json("POST", "/docx/v1/documents", payload=payload)
        created = as_dict(as_dict(response.get("data")).get("document"))
        document_id = str(created.get("document_id", "")).strip()
        if not document_id:
            raise StoreError(f"飞书文档创建成功但未返回 document_id: {name}")
        doc["document_id"] = document_id
        if not str(doc.get("title", "")).strip():
            doc["title"] = payload["title"]
        self.config.save()
        return doc

    def _document_root_children_count(self, document_id: str) -> int:
        page_token: str | None = None
        while True:
            query: dict[str, Any] = {"page_size": 500, "document_revision_id": -1}
            if page_token:
                query["page_token"] = page_token
            response = self._request_json("GET", f"/docx/v1/documents/{document_id}/blocks", query=query)
            data = as_dict(response.get("data"))
            for item in as_list(data.get("items")):
                block = as_dict(item)
                if str(block.get("block_id", "")).strip() == document_id:
                    return len(as_list(block.get("children")))
            if not data.get("has_more"):
                break
            page_token = str(data.get("page_token") or "").strip() or None
            if not page_token:
                break
        raise StoreError(f"飞书文档未找到根块，无法原地更新: {document_id}")

    def _clear_document_children(self, document_id: str) -> None:
        remaining = self._document_root_children_count(document_id)
        while remaining > 0:
            end_index = min(50, remaining)
            self._request_json(
                "DELETE",
                f"/docx/v1/documents/{document_id}/blocks/{document_id}/children/batch_delete",
                query={"document_revision_id": -1, "client_token": str(uuid.uuid4())},
                payload={"start_index": 0, "end_index": end_index},
            )
            remaining -= end_index

    def _append_doc_blocks(self, document_id: str, blocks: list[dict[str, Any]]) -> None:
        for chunk in chunked(blocks, 50):
            self._request_json(
                "POST",
                f"/docx/v1/documents/{document_id}/blocks/{document_id}/children",
                query={"document_revision_id": -1, "client_token": str(uuid.uuid4())},
                payload={"children": chunk},
            )

    def _batch_create_table_records(self, table: dict[str, Any], records: list[dict[str, Any]]) -> None:
        normalized: list[dict[str, Any]] = []
        for record in records:
            fields = {key: value for key, value in record.items() if key != "record_id"}
            if fields:
                normalized.append({"fields": fields})
        for chunk in chunked(normalized, FEISHU_TABLE_RECORD_BATCH_SIZE):
            self._request_json(
                "POST",
                f"/bitable/v1/apps/{table['app_token']}/tables/{table['table_id']}/records/batch_create",
                query={"user_id_type": self.config.user_id_type, "client_token": str(uuid.uuid4())},
                payload={"records": chunk},
            )

    def _batch_update_table_records(self, table: dict[str, Any], records: list[dict[str, Any]]) -> None:
        normalized: list[dict[str, Any]] = []
        for record in records:
            record_id = str(record.get("record_id", "")).strip()
            fields = {key: value for key, value in record.items() if key != "record_id"}
            if record_id and fields:
                normalized.append({"record_id": record_id, "fields": fields})
        for chunk in chunked(normalized, FEISHU_TABLE_RECORD_BATCH_SIZE):
            self._request_json(
                "POST",
                f"/bitable/v1/apps/{table['app_token']}/tables/{table['table_id']}/records/batch_update",
                query={"user_id_type": self.config.user_id_type},
                payload={"records": chunk},
            )

    def _batch_delete_table_records(self, table: dict[str, Any], record_ids: list[str]) -> None:
        for chunk in chunked(record_ids, FEISHU_TABLE_RECORD_BATCH_SIZE):
            self._request_json(
                "POST",
                f"/bitable/v1/apps/{table['app_token']}/tables/{table['table_id']}/records/batch_delete",
                query={"user_id_type": self.config.user_id_type},
                payload={"records": chunk},
            )

    def _require_table(self, name: str) -> dict[str, Any]:
        table = self.config.tables.get(name)
        if not isinstance(table, dict):
            raise StoreError(f"飞书表格目标未配置: {name}")
        app_token = str(table.get("app_token", "")).strip()
        table_id = str(table.get("table_id", "")).strip()
        if not app_token or not table_id:
            raise StoreError(f"飞书表格目标缺少 app_token/table_id: {name}")
        return table

    def _require_doc(self, name: str, *, allow_missing_document_id: bool = False) -> dict[str, Any]:
        doc = self.config.docs.get(name)
        if not isinstance(doc, dict):
            raise StoreError(f"飞书文档目标未配置: {name}")
        if allow_missing_document_id:
            return doc
        if not str(doc.get("document_id", "")).strip():
            raise StoreError(f"飞书文档目标缺少 document_id: {name}")
        return doc

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        use_auth: bool = True,
        api_base: str | None = None,
    ) -> dict[str, Any]:
        url = build_url(api_base or self.config.api_base, path, query)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        headers = {}
        if payload is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        if use_auth:
            headers["Authorization"] = f"Bearer {self._access_token()}"

        for attempt in range(self.config.max_retries + 1):
            req = request.Request(url, data=body, headers=headers, method=method)
            try:
                with request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
            except error.HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="replace")
                response_body = parse_json_safely(raw)
                response_code = int(response_body.get("code", -1)) if isinstance(response_body, dict) else -1
                if self._should_retry(exc.code, response_code, attempt):
                    time.sleep(backoff_seconds(attempt))
                    continue
                if exc.code == 403 and response_code == 1770032:
                    raise StoreError(
                        f"飞书接口权限不足 {method} {url}: code={response_code}, msg={as_dict(response_body).get('msg', '')}。"
                        "请确认应用已开通目标 API 权限，且目标文档已授权该应用或机器人可编辑。"
                    ) from exc
                raise StoreError(f"飞书接口调用失败 {method} {url}: status={exc.code}, body={raw}") from exc
            except error.URLError as exc:
                if attempt < self.config.max_retries:
                    time.sleep(backoff_seconds(attempt))
                    continue
                raise StoreError(f"飞书接口网络异常 {method} {url}: {exc}") from exc

            data = parse_json_safely(raw)
            if not isinstance(data, dict):
                raise StoreError(f"飞书接口返回非 JSON 响应 {method} {url}: {raw}")
            code = int(data.get("code", 0))
            if code == 0:
                return data
            if self._should_retry(200, code, attempt):
                time.sleep(backoff_seconds(attempt))
                continue
            if code == 1770032:
                raise StoreError(
                    f"飞书接口权限不足 {method} {url}: code={code}, msg={data.get('msg', '')}。"
                    "请确认应用已开通目标 API 权限，且目标文档已授权该应用或机器人可编辑。"
                )
            raise StoreError(f"飞书接口业务失败 {method} {url}: code={code}, msg={data.get('msg', '')}")

        raise StoreError(f"飞书接口重试后仍失败: {method} {url}")

    def _should_retry(self, http_status: int, feishu_code: int, attempt: int) -> bool:
        if attempt >= self.config.max_retries:
            return False
        return http_status in RETRYABLE_HTTP_STATUSES or feishu_code in RETRYABLE_FEISHU_CODES

    def _access_token(self) -> str:
        if self.config.tenant_access_token:
            return self.config.tenant_access_token

        fixed_token_env = self.config.tenant_access_token_env
        if fixed_token_env:
            fixed_token = env_value(fixed_token_env, self.root)
            if fixed_token:
                return fixed_token

        now = time.time()
        if self._tenant_access_token and now < self._token_expires_at:
            return self._tenant_access_token

        app_id = self.config.app_id or env_value(self.config.app_id_env, self.root)
        app_secret = self.config.app_secret or env_value(self.config.app_secret_env, self.root)
        if not app_id or not app_secret:
            raise StoreError(
                "飞书凭证缺失，请配置应用环境变量。"
                f" 需要 {self.config.app_id_env} / {self.config.app_secret_env}"
            )

        auth_base = strip_open_apis(self.config.api_base)
        response = self._request_json(
            "POST",
            "/open-apis/auth/v3/tenant_access_token/internal",
            payload={"app_id": app_id, "app_secret": app_secret},
            use_auth=False,
            api_base=auth_base,
        )
        token = str(response.get("tenant_access_token", "")).strip()
        expire_seconds = int(response.get("expire", 7200))
        if not token:
            raise StoreError("获取飞书 tenant_access_token 失败：响应中缺少 tenant_access_token")
        self._tenant_access_token = token
        self._token_expires_at = now + max(60, expire_seconds - 60)
        return token


def build_url(base: str, path: str, query: dict[str, Any] | None) -> str:
    url = base.rstrip("/") + "/" + path.lstrip("/")
    if not query:
        return url
    encoded = parse.urlencode(
        [(key, value) for key, value in query.items() if value is not None and str(value) != ""],
        doseq=True,
    )
    if not encoded:
        return url
    return f"{url}?{encoded}"


def strip_open_apis(api_base: str) -> str:
    if api_base.endswith("/open-apis"):
        return api_base[: -len("/open-apis")]
    return api_base
