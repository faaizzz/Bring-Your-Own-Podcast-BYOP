"""Object storage seam: everything that stores media (covers, audio, previews) goes through it."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

DEFAULT_CHUNK_SIZE = 64 * 1024


class StorageError(Exception):
    """The backend failed (unreachable, access denied, ...)."""


class StorageKeyNotFound(StorageError):
    pass


@dataclass(frozen=True)
class ObjectInfo:
    size: int
    content_type: str | None


class Storage(Protocol):
    """Keys look like paths (`shows/<id>/cover.jpg`); the backend decides where bytes live."""

    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        """Store `data`, replacing any previous object (readers never see a partial write)."""
        ...

    async def get(self, key: str) -> bytes | None:
        """The whole object, or None when it does not exist. For small objects only."""
        ...

    def get_stream(self, key: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> AsyncIterator[bytes]:
        """The object in chunks; raises `StorageKeyNotFound` if it does not exist."""
        ...

    async def head(self, key: str) -> ObjectInfo | None:
        """Size and content type, or None when the object does not exist."""
        ...

    async def exists(self, key: str) -> bool: ...

    async def delete(self, key: str) -> None:
        """Remove one object; a missing key is not an error."""
        ...

    async def delete_prefix(self, prefix: str) -> None:
        """Remove every object under `prefix/`. Nothing matching is not an error."""
        ...

    async def url_for(self, key: str, *, expires_in: int = 3600) -> str | None:
        """A time-limited direct URL for clients, or None when the API must serve the bytes."""
        ...


def show_prefix(show_id: uuid.UUID) -> str:
    """Key prefix under which everything a show owns (audio, cover, ...) is stored."""
    return f"shows/{show_id}"


def cover_key(show_id: uuid.UUID) -> str:
    return f"{show_prefix(show_id)}/cover.jpg"


def validate_key(key: str) -> str:
    """Reject keys that could escape the storage root or name nothing."""
    parts = key.split("/")
    if (
        not key
        or key.startswith("/")
        or "\\" in key
        or "\x00" in key
        or any(part in ("", ".", "..") for part in parts)
    ):
        raise ValueError(f"invalid storage key: {key!r}")
    return key
