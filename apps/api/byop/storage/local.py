import mimetypes
import shutil
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import anyio
import anyio.to_thread

from byop.storage.base import DEFAULT_CHUNK_SIZE, ObjectInfo, StorageKeyNotFound, validate_key


class LocalStorage:
    """Files below `MEDIA_ROOT` (the media volume)."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        """The file for `key`; it can never leave the media root or be the root itself."""
        validate_key(key)
        target = (self._root / key).resolve()
        if target == self._root or not target.is_relative_to(self._root):
            raise ValueError(f"key escapes the media root: {key!r}")
        return target

    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        path = anyio.Path(self._path(key))
        await path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(f"{path.name}.{uuid.uuid4().hex}.part")
        try:
            await partial.write_bytes(data)
            await partial.replace(path)
        finally:
            await partial.unlink(missing_ok=True)

    async def put_file(self, key: str, path: Path, *, content_type: str | None = None) -> None:
        target = anyio.Path(self._path(key))
        await target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f"{target.name}.{uuid.uuid4().hex}.part")
        try:
            await anyio.to_thread.run_sync(shutil.copyfile, path, partial)
            await partial.replace(target)
        finally:
            await partial.unlink(missing_ok=True)

    async def get_file(self, key: str, path: Path) -> bool:
        source = self._path(key)
        if not await anyio.Path(source).is_file():
            return False
        await anyio.to_thread.run_sync(shutil.copyfile, source, path)
        return True

    async def get(self, key: str) -> bytes | None:
        try:
            return await anyio.Path(self._path(key)).read_bytes()
        except (FileNotFoundError, IsADirectoryError):
            return None

    async def get_stream(
        self, key: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE
    ) -> AsyncIterator[bytes]:
        try:
            handle = await anyio.open_file(self._path(key), "rb")
        except (FileNotFoundError, IsADirectoryError) as exc:
            raise StorageKeyNotFound(key) from exc
        async with handle:
            while chunk := await handle.read(chunk_size):
                yield chunk

    async def head(self, key: str) -> ObjectInfo | None:
        path = anyio.Path(self._path(key))
        try:
            stat = await path.stat()
        except FileNotFoundError:
            return None
        if not await path.is_file():
            return None
        return ObjectInfo(stat.st_size, mimetypes.guess_type(key)[0])

    async def exists(self, key: str) -> bool:
        return await self.head(key) is not None

    async def delete(self, key: str) -> None:
        await anyio.Path(self._path(key)).unlink(missing_ok=True)

    async def delete_prefix(self, prefix: str) -> None:
        target = self._path(prefix)
        if await anyio.Path(target).is_dir():
            await anyio.to_thread.run_sync(shutil.rmtree, target, True)

    async def url_for(self, key: str, *, expires_in: int = 3600) -> str | None:
        self._path(key)
        return None  # served by the API
