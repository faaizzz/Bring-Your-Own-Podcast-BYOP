"""Media storage. This is the minimal seam other services depend on; backends grow here."""

import shutil
import uuid
from pathlib import Path
from typing import Protocol

import anyio
import anyio.to_thread


class Storage(Protocol):
    async def read(self, key: str) -> bytes | None:
        """The object's bytes, or None when it does not exist."""
        ...

    async def write(self, key: str, data: bytes) -> None:
        """Store `data` under `key`, replacing any previous object (atomically)."""
        ...

    async def delete_prefix(self, prefix: str) -> None:
        """Remove every object whose key starts with `prefix/`. Missing keys are not an error."""
        ...


def show_prefix(show_id: uuid.UUID) -> str:
    """Key prefix under which everything a show owns (audio, cover, ...) is stored."""
    return f"shows/{show_id}"


class LocalStorage:
    """Files below `MEDIA_ROOT`."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        """The file for `key`; keys can never leave the media root or name the root itself."""
        target = (self._root / key).resolve()
        if target == self._root or not target.is_relative_to(self._root):
            raise ValueError(f"key escapes the media root: {key!r}")
        return target

    async def read(self, key: str) -> bytes | None:
        path = anyio.Path(self._path(key))
        try:
            return await path.read_bytes()
        except (FileNotFoundError, IsADirectoryError):
            return None

    async def write(self, key: str, data: bytes) -> None:
        path = anyio.Path(self._path(key))
        await path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(f"{path.name}.{uuid.uuid4().hex}.part")
        try:
            await partial.write_bytes(data)
            await partial.replace(path)
        finally:
            await partial.unlink(missing_ok=True)

    async def delete_prefix(self, prefix: str) -> None:
        target = self._path(prefix)
        if await anyio.Path(target).exists():
            await anyio.to_thread.run_sync(shutil.rmtree, target, True)
