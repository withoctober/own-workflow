"""External service integrations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from workflow.integrations.s3 import S3UploadConfig, S3UploadedObject, S3Uploader


def fetch_daily_hotspots(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from workflow.integrations.hotspots import fetch_daily_hotspots as _fetch_daily_hotspots

    return _fetch_daily_hotspots(*args, **kwargs)


def build_s3_uploader(*args: Any, **kwargs: Any):
    from workflow.integrations.s3 import build_s3_uploader as _build_s3_uploader

    return _build_s3_uploader(*args, **kwargs)


def generate_images(*args: Any, **kwargs: Any):
    from workflow.integrations.image_generation import generate_images as _generate_images

    return _generate_images(*args, **kwargs)


def load_s3_upload_config(*args: Any, **kwargs: Any):
    from workflow.integrations.s3 import load_s3_upload_config as _load_s3_upload_config

    return _load_s3_upload_config(*args, **kwargs)


def __getattr__(name: str) -> Any:
    if name in {"S3UploadConfig", "S3UploadedObject", "S3Uploader"}:
        from workflow.integrations import s3 as s3_module

        return getattr(s3_module, name)
    raise AttributeError(name)


__all__ = [
    "S3UploadConfig",
    "S3UploadedObject",
    "S3Uploader",
    "build_s3_uploader",
    "fetch_daily_hotspots",
    "generate_images",
    "load_s3_upload_config",
]
