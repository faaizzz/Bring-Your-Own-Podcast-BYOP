from functools import lru_cache

from byop.config import Settings
from byop.storage.base import (
    DEFAULT_CHUNK_SIZE,
    ObjectInfo,
    Storage,
    StorageError,
    StorageKeyNotFound,
    cover_key,
    show_prefix,
    validate_key,
)
from byop.storage.local import LocalStorage
from byop.storage.s3 import S3Storage


@lru_cache
def _build_s3(
    bucket: str,
    access_key_id: str,
    secret_access_key: str,
    region: str,
    endpoint_url: str | None,
    public_endpoint_url: str | None,
) -> S3Storage:
    return S3Storage(
        bucket=bucket,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        region=region,
        endpoint_url=endpoint_url,
        public_endpoint_url=public_endpoint_url,
    )


def build_storage(settings: Settings) -> Storage:
    """The backend selected by `STORAGE_BACKEND`. S3 clients are reused across requests."""
    if settings.storage_backend == "s3":
        assert settings.s3_bucket and settings.s3_access_key_id and settings.s3_secret_access_key
        return _build_s3(
            settings.s3_bucket,
            settings.s3_access_key_id,
            settings.s3_secret_access_key.get_secret_value(),
            settings.s3_region,
            settings.s3_endpoint_url,
            settings.s3_public_endpoint_url,
        )
    return LocalStorage(settings.media_root)


__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "LocalStorage",
    "ObjectInfo",
    "S3Storage",
    "Storage",
    "StorageError",
    "StorageKeyNotFound",
    "build_storage",
    "cover_key",
    "show_prefix",
    "validate_key",
]
