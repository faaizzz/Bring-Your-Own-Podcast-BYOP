"""Media storage. This is the minimal seam other services depend on; backends grow here."""

import shutil
import uuid
from pathlib import Path
from typing import Protocol

import anyio
import anyio.to_thread


class Storage(Protocol):
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

    async def delete_prefix(self, prefix: str) -> None:
        target = (self._root / prefix).resolve()
        if target == self._root or not target.is_relative_to(self._root):
            raise ValueError(f"refusing to delete outside the media root: {prefix!r}")
        if await anyio.Path(target).exists():
            await anyio.to_thread.run_sync(shutil.rmtree, target, True)
