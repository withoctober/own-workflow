from __future__ import annotations

import hashlib
import hmac
import mimetypes
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib import error, parse, request

from workflow.store import StoreError


DOWNLOAD_USER_AGENT = "OpenClaw-S3Uploader/1.0"
DEFAULT_TIMEOUT_SECONDS = 300
SERVICE_NAME = "s3"
CONTENT_TYPE_ALIASES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
}


@dataclass(frozen=True)
class S3UploadConfig:
    endpoint: str
    region: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    session_token: str = ""
    key_prefix: str = ""
    public_base_url: str = ""


@dataclass(frozen=True)
class S3UploadedObject:
    bucket: str
    key: str
    url: str
    etag: str
    content_type: str
    size: int


def _first_non_empty(values: Iterable[str]) -> str:
    for value in values:
        normalized = str(value).strip()
        if normalized:
            return normalized
    return ""


def _env_value(name: str, root: Path) -> str:
    value = os.environ.get(name)
    if value:
        return value
    env_file = root / ".env"
    if not env_file.exists():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if not line or line.strip().startswith("#") or "=" not in line:
            continue
        key, raw = line.split("=", 1)
        if key.strip() == name:
            return raw.strip().strip("'\"")
    return ""


def _read_config_value(
    root: Path,
    names: tuple[str, ...],
    *,
    required: bool = False,
) -> str:
    value = _first_non_empty(_env_value(name, root) for name in names)
    if required and not value:
        raise StoreError(f"缺少 {names[0]}，无法上传图片到 S3")
    return value


def load_s3_upload_config(root: Path) -> S3UploadConfig:
    endpoint = _read_config_value(root, ("S3_ENDPOINT",), required=True).rstrip("/")
    region = _read_config_value(root, ("S3_REGION", "AWS_REGION"), required=True)
    bucket = _read_config_value(root, ("S3_BUCKET",), required=True)
    access_key_id = _read_config_value(root, ("S3_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID"), required=True)
    secret_access_key = _read_config_value(
        root,
        ("S3_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY"),
        required=True,
    )
    session_token = _read_config_value(root, ("S3_SESSION_TOKEN", "AWS_SESSION_TOKEN"))
    key_prefix = _read_config_value(root, ("S3_KEY_PREFIX",)).strip("/")
    public_base_url = _read_config_value(root, ("S3_PUBLIC_BASE_URL",)).rstrip("/")

    parsed = parse.urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise StoreError("S3_ENDPOINT 必须是合法的 http/https URL")

    return S3UploadConfig(
        endpoint=endpoint,
        region=region,
        bucket=bucket,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        session_token=session_token,
        key_prefix=key_prefix,
        public_base_url=public_base_url,
    )


def build_s3_uploader(root: Path, tenant_config=None) -> "S3Uploader":
    return S3Uploader(load_s3_upload_config(root))


class S3Uploader:
    def __init__(self, config: S3UploadConfig) -> None:
        self.config = config
        self._endpoint = parse.urlsplit(config.endpoint)
        self._virtual_host = self._build_virtual_host()

    def upload_from_url(
        self,
        source_url: str,
        object_key: str,
        *,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        content_type: str = "",
    ) -> S3UploadedObject:
        download_request = request.Request(
            str(source_url).strip(),
            headers={"User-Agent": DOWNLOAD_USER_AGENT},
            method="GET",
        )
        try:
            with request.urlopen(download_request, timeout=timeout) as response:
                data = response.read()
                detected_content_type = str(response.headers.get("Content-Type", "")).split(";", 1)[0].strip()
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise StoreError(f"S3 上传前下载图片失败: HTTP {exc.code}; body={detail[:300].strip()}") from exc
        except error.URLError as exc:
            raise StoreError(f"S3 上传前下载图片失败: {exc}") from exc

        normalized_content_type = content_type.strip() or detected_content_type or "application/octet-stream"
        normalized_key = self._ensure_object_key_extension(str(object_key).strip(), normalized_content_type, str(source_url))
        return self.upload_bytes(data, normalized_key, content_type=normalized_content_type, timeout=timeout)

    def upload_bytes(
        self,
        data: bytes,
        object_key: str,
        *,
        content_type: str = "application/octet-stream",
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> S3UploadedObject:
        normalized_key = self._normalize_object_key(object_key)
        payload_hash = hashlib.sha256(data).hexdigest()
        amz_datetime = datetime.now(timezone.utc)
        amz_date = amz_datetime.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = amz_datetime.strftime("%Y%m%d")

        canonical_uri = self._build_canonical_uri(normalized_key)
        request_url = parse.urlunsplit(
            (self._endpoint.scheme, self._virtual_host, canonical_uri, "", "")
        )
        signed_headers = {
            "content-type": content_type.strip() or "application/octet-stream",
            "host": self._virtual_host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if self.config.session_token:
            signed_headers["x-amz-security-token"] = self.config.session_token

        header_names = sorted(signed_headers)
        canonical_headers = "".join(f"{name}:{signed_headers[name].strip()}\n" for name in header_names)
        signed_header_names = ";".join(header_names)
        canonical_request = "\n".join(
            [
                "PUT",
                canonical_uri,
                "",
                canonical_headers,
                signed_header_names,
                payload_hash,
            ]
        )
        credential_scope = f"{date_stamp}/{self.config.region}/{SERVICE_NAME}/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        authorization = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.config.access_key_id}/{credential_scope}, "
            f"SignedHeaders={signed_header_names}, "
            f"Signature={self._signature(string_to_sign, date_stamp)}"
        )

        request_headers = {
            "Authorization": authorization,
            "Content-Type": signed_headers["content-type"],
            "Host": signed_headers["host"],
            "X-Amz-Content-SHA256": signed_headers["x-amz-content-sha256"],
            "X-Amz-Date": signed_headers["x-amz-date"],
        }
        if self.config.session_token:
            request_headers["X-Amz-Security-Token"] = self.config.session_token

        upload_request = request.Request(
            request_url,
            data=data,
            headers=request_headers,
            method="PUT",
        )
        try:
            with request.urlopen(upload_request, timeout=timeout) as response:
                etag = str(response.headers.get("ETag", "")).strip()
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise StoreError(f"S3 上传失败: HTTP {exc.code}; body={detail[:300].strip()}") from exc
        except error.URLError as exc:
            raise StoreError(f"S3 上传失败: {exc}") from exc

        return S3UploadedObject(
            bucket=self.config.bucket,
            key=normalized_key,
            url=self._public_url(normalized_key),
            etag=etag,
            content_type=request_headers["Content-Type"],
            size=len(data),
        )

    def _normalize_object_key(self, object_key: str) -> str:
        normalized = str(object_key).strip().replace("\\", "/").strip("/")
        if not normalized:
            raise StoreError("S3 object key 不能为空")
        if self.config.key_prefix:
            return f"{self.config.key_prefix}/{normalized}".strip("/")
        return normalized

    def _build_virtual_host(self) -> str:
        netloc = self._endpoint.netloc.strip()
        bucket = self.config.bucket.strip()
        if not bucket:
            raise StoreError("S3_BUCKET 不能为空")
        if netloc.startswith(f"{bucket}."):
            return netloc
        return f"{bucket}.{netloc}"

    def _build_canonical_uri(self, object_key: str) -> str:
        path_parts: list[str] = []
        endpoint_path = self._endpoint.path.strip("/")
        if endpoint_path:
            path_parts.extend(endpoint_path.split("/"))
        path_parts.extend(part for part in object_key.split("/") if part)
        encoded = [parse.quote(part, safe="-_.~") for part in path_parts]
        return "/" + "/".join(encoded)

    def _public_url(self, object_key: str) -> str:
        encoded_key = "/".join(parse.quote(part, safe="-_.~") for part in object_key.split("/") if part)
        if self.config.public_base_url:
            return f"{self.config.public_base_url}/{encoded_key}".rstrip("/")
        return parse.urlunsplit(
            (
                self._endpoint.scheme,
                self._virtual_host,
                self._build_canonical_uri(object_key),
                "",
                "",
            )
        )

    def _ensure_object_key_extension(self, object_key: str, content_type: str, source_url: str) -> str:
        path = Path(object_key)
        if path.suffix:
            return object_key
        extension = self._guess_extension(content_type, source_url)
        return f"{object_key}{extension}" if extension else object_key

    def _guess_extension(self, content_type: str, source_url: str) -> str:
        normalized_content_type = str(content_type).strip().lower()
        if normalized_content_type in CONTENT_TYPE_ALIASES:
            return CONTENT_TYPE_ALIASES[normalized_content_type]
        guessed = mimetypes.guess_extension(normalized_content_type, strict=False) if normalized_content_type else ""
        if guessed:
            return ".jpg" if guessed == ".jpe" else guessed
        source_path = parse.urlsplit(source_url).path
        return Path(source_path).suffix.lower()

    def _signature(self, string_to_sign: str, date_stamp: str) -> str:
        key_date = hmac.new(
            f"AWS4{self.config.secret_access_key}".encode("utf-8"),
            date_stamp.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        key_region = hmac.new(key_date, self.config.region.encode("utf-8"), hashlib.sha256).digest()
        key_service = hmac.new(key_region, SERVICE_NAME.encode("utf-8"), hashlib.sha256).digest()
        signing_key = hmac.new(key_service, b"aws4_request", hashlib.sha256).digest()
        return hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()


__all__ = [
    "S3UploadConfig",
    "S3UploadedObject",
    "S3Uploader",
    "build_s3_uploader",
    "load_s3_upload_config",
]
