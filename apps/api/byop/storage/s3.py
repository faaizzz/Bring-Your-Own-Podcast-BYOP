"""S3-compatible object storage (AWS S3, MinIO, RustFS, ...) through boto3.

boto3 is synchronous, so every call runs in a worker thread.
"""

import threading
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

import anyio.to_thread
import boto3
import structlog
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from byop.storage.base import (
    DEFAULT_CHUNK_SIZE,
    ObjectInfo,
    StorageError,
    StorageKeyNotFound,
    validate_key,
)

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client
    from mypy_boto3_s3.type_defs import ObjectIdentifierTypeDef

log = structlog.get_logger(__name__)

T = TypeVar("T")
_MISSING_CODES = {"404", "NoSuchKey", "NotFound", "NoSuchBucket"}
_DELETE_BATCH = 1000  # the S3 limit for one DeleteObjects call


def _code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


class S3Storage:
    def __init__(
        self,
        *,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        region: str = "us-east-1",
        endpoint_url: str | None = None,
        public_endpoint_url: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._endpoint_url = endpoint_url
        # Servers like MinIO need path-style addressing (http://host/bucket/key).
        config = Config(
            s3={"addressing_style": "path" if endpoint_url else "auto"},
            retries={"max_attempts": 3, "mode": "standard"},
            signature_version="s3v4",
        )

        def client(url: str | None) -> "S3Client":
            return boto3.client(
                "s3",
                endpoint_url=url,
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                region_name=region,
                config=config,
            )

        self._client = client(endpoint_url)
        # Links handed to browsers must use an address the browser can reach.
        self._signer = client(public_endpoint_url) if public_endpoint_url else self._client
        self._bucket_ready = endpoint_url is None  # only self-hosted servers get auto-created
        self._bucket_lock = threading.Lock()

    async def _run(self, func: Callable[[], T]) -> T:
        try:
            return await anyio.to_thread.run_sync(func)
        except ClientError as exc:
            if _code(exc) in _MISSING_CODES:
                raise StorageKeyNotFound(str(exc)) from exc
            raise StorageError(f"Object storage request failed: {_code(exc) or exc}") from exc
        except BotoCoreError as exc:
            raise StorageError(f"Could not reach object storage: {exc}") from exc

    def _ensure_bucket(self) -> None:
        with self._bucket_lock:
            if self._bucket_ready:
                return
            try:
                self._client.head_bucket(Bucket=self._bucket)
            except ClientError as exc:
                if _code(exc) not in _MISSING_CODES:
                    raise
                log.info("s3_bucket_create", bucket=self._bucket)
                self._client.create_bucket(Bucket=self._bucket)
            self._bucket_ready = True

    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        validate_key(key)

        def upload() -> None:
            self._ensure_bucket()
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type or "application/octet-stream",
            )

        await self._run(upload)

    async def put_file(self, key: str, path: Path, *, content_type: str | None = None) -> None:
        validate_key(key)

        def upload() -> None:
            self._ensure_bucket()
            extra = {"ContentType": content_type} if content_type else {}
            # upload_file streams from disk and switches to multipart for large files
            self._client.upload_file(str(path), self._bucket, key, ExtraArgs=extra or None)

        await self._run(upload)

    async def get_file(self, key: str, path: Path) -> bool:
        validate_key(key)
        try:
            await self._run(lambda: self._client.download_file(self._bucket, key, str(path)))
        except StorageKeyNotFound:
            return False
        return True

    async def get(self, key: str) -> bytes | None:
        validate_key(key)

        def download() -> bytes:
            return self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()

        try:
            return await self._run(download)
        except StorageKeyNotFound:
            return None

    async def get_stream(
        self, key: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE
    ) -> AsyncIterator[bytes]:
        validate_key(key)
        body = await self._run(
            lambda: self._client.get_object(Bucket=self._bucket, Key=key)["Body"]
        )
        chunks = body.iter_chunks(chunk_size)
        done = object()
        try:
            while True:
                chunk = await self._run(lambda: next(chunks, done))
                if chunk is done:
                    break
                assert isinstance(chunk, bytes)
                yield chunk
        finally:
            await anyio.to_thread.run_sync(body.close)

    async def head(self, key: str) -> ObjectInfo | None:
        validate_key(key)
        try:
            meta = await self._run(lambda: self._client.head_object(Bucket=self._bucket, Key=key))
        except StorageKeyNotFound:
            return None
        return ObjectInfo(int(meta["ContentLength"]), meta.get("ContentType"))

    async def exists(self, key: str) -> bool:
        return await self.head(key) is not None

    async def delete(self, key: str) -> None:
        validate_key(key)
        await self._run(lambda: self._client.delete_object(Bucket=self._bucket, Key=key))

    async def delete_prefix(self, prefix: str) -> None:
        validate_key(prefix)

        def purge() -> None:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket, Prefix=f"{prefix}/"):
                keys: list[ObjectIdentifierTypeDef] = [
                    {"Key": obj["Key"]} for obj in page.get("Contents", [])
                ]
                for start in range(0, len(keys), _DELETE_BATCH):
                    self._client.delete_objects(
                        Bucket=self._bucket,
                        Delete={"Objects": keys[start : start + _DELETE_BATCH], "Quiet": True},
                    )

        try:
            await self._run(purge)
        except StorageKeyNotFound:
            return  # no bucket, so nothing to remove

    async def url_for(self, key: str, *, expires_in: int = 3600) -> str | None:
        validate_key(key)
        return self._signer.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )
