import mimetypes
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal, get_args

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Show
from byop.services.ffmpeg import FFmpegError, probe
from byop.services.shows import ShowNotFound, ShowView, get_show
from byop.storage import ObjectInfo, Storage, show_prefix

AudioKind = Literal["intro", "outro", "music"]
AUDIO_KINDS: tuple[str, ...] = get_args(AudioKind)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
# A jingle is short; a music bed may be long (it is looped under the speech).
MAX_SECONDS: dict[str, int] = {"intro": 120, "outro": 120, "music": 1800}
SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac"}


class AudioInvalid(Exception):
    """The upload cannot be used (maps to 422)."""


class AudioTooLarge(AudioInvalid):
    """The upload is bigger than `MAX_UPLOAD_BYTES` (maps to 413)."""


def key_of(show: Show, kind: str) -> str | None:
    return {"intro": show.intro_key, "outro": show.outro_key, "music": show.music_key}[kind]


def _assign(view: ShowView, kind: str, key: str | None) -> None:
    show = view.show
    if kind == "intro":
        show.intro_key = key
    elif kind == "outro":
        show.outro_key = key
    else:
        show.music_key = key
    show.updated_at = func.now()  # changes the asset URL's version


def asset_key(show_id: uuid.UUID, kind: str, suffix: str) -> str:
    return f"{show_prefix(show_id)}/audio/{kind}{suffix}"


async def set_asset(
    session: AsyncSession,
    storage: Storage,
    user_id: uuid.UUID,
    show_id: uuid.UUID,
    kind: str,
    source: Path,
    filename: str,
) -> ShowView:
    """Check the uploaded file at `source` and make it the show's `kind` clip."""
    view = await get_show(session, user_id, show_id)  # 404 for someone else's show
    suffix = Path(filename).suffix.lower()
    if suffix not in SUFFIXES:
        raise AudioInvalid(
            f"Use an audio file ({', '.join(sorted(s.lstrip('.') for s in SUFFIXES))}); "
            f"“{filename}” is not one"
        )
    try:
        seconds, has_audio = await probe(source)
    except FFmpegError as exc:
        raise AudioInvalid("The file is not readable audio") from exc
    if not has_audio:
        raise AudioInvalid("The file has no audio in it")
    limit = MAX_SECONDS[kind]
    if seconds > limit:
        raise AudioInvalid(
            f"The {kind} clip is {seconds / 60:.1f} minutes long; the most allowed is "
            f"{limit // 60} minutes"
        )
    key = asset_key(show_id, kind, suffix)
    previous = key_of(view.show, kind)
    await storage.put_file(key, source, content_type=mimetypes.guess_type(key)[0] or "audio/mpeg")
    if previous and previous != key:
        await storage.delete(previous)  # replaced by a file of another format
    _assign(view, kind, key)
    await session.commit()
    return await get_show(session, user_id, show_id, refresh=True)


async def remove_asset(
    session: AsyncSession, storage: Storage, user_id: uuid.UUID, show_id: uuid.UUID, kind: str
) -> ShowView:
    view = await get_show(session, user_id, show_id)
    key = key_of(view.show, kind)
    if key:
        await storage.delete(key)
        _assign(view, kind, None)
        await session.commit()
    return await get_show(session, user_id, show_id, refresh=True)


async def open_asset(
    session: AsyncSession, storage: Storage, user_id: uuid.UUID, show_id: uuid.UUID, kind: str
) -> tuple[ObjectInfo, AsyncIterator[bytes]]:
    """The clip's bytes, for the owner to preview."""
    view = await get_show(session, user_id, show_id)
    key = key_of(view.show, kind)
    info = await storage.head(key) if key else None
    if key is None or info is None:
        raise ShowNotFound
    return info, storage.get_stream(key)
