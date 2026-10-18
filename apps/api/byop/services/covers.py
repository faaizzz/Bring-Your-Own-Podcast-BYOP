import io
import uuid
from collections.abc import AsyncIterator

import anyio.to_thread
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Show
from byop.services.shows import ShowNotFound, ShowView, get_show
from byop.storage import ObjectInfo, Storage, cover_key

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# Podcast directories want a square between 1400 and 3000 pixels; smaller sources are scaled up
# only if they are not hopelessly small.
MIN_SOURCE_SIDE = 600
MIN_OUTPUT_SIDE = 1400
MAX_OUTPUT_SIDE = 3000
MAX_SOURCE_PIXELS = 64_000_000  # refuse decompression bombs before decoding
ALLOWED_FORMATS = {"PNG", "JPEG"}
JPEG_QUALITY = 90


class CoverInvalid(Exception):
    """The upload cannot be used as a cover (maps to 422)."""


class CoverTooLarge(CoverInvalid):
    """The upload is bigger than `MAX_UPLOAD_BYTES` (maps to 413)."""


def process_cover(data: bytes) -> bytes:
    """A square JPEG of 1400-3000 px made from a PNG/JPEG upload (CPU-bound: run in a thread)."""
    if not data:
        raise CoverInvalid("The file is empty")
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in ALLOWED_FORMATS:
                found = source.format or "unknown"
                raise CoverInvalid(f"Use a PNG or JPEG image (this file is {found})")
            width, height = source.size
            if width * height > MAX_SOURCE_PIXELS:
                raise CoverInvalid(f"The image is too large ({width}x{height} pixels)")
            if min(width, height) < MIN_SOURCE_SIDE:
                raise CoverInvalid(
                    f"The image is too small ({width}x{height}); it must be at least "
                    f"{MIN_SOURCE_SIDE}x{MIN_SOURCE_SIDE} pixels"
                    f" (podcast directories want {MIN_OUTPUT_SIDE}-{MAX_OUTPUT_SIDE})"
                )
            source.load()
            upright = ImageOps.exif_transpose(source)
    except CoverInvalid:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise CoverInvalid("The file is not a readable PNG or JPEG image") from exc

    if upright.mode in ("RGBA", "LA", "P"):
        rgba = upright.convert("RGBA")
        flat = Image.new("RGB", rgba.size, "white")  # directories do not support transparency
        flat.paste(rgba, mask=rgba.getchannel("A"))
        picture = flat
    else:
        picture = upright.convert("RGB")

    side = min(picture.size)
    left, top = (picture.width - side) // 2, (picture.height - side) // 2
    square = picture.crop((left, top, left + side, top + side))
    target = min(max(side, MIN_OUTPUT_SIDE), MAX_OUTPUT_SIDE)
    if target != side:
        square = square.resize((target, target), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    square.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)  # metadata is dropped
    return out.getvalue()


async def set_cover(
    session: AsyncSession,
    storage: Storage,
    user_id: uuid.UUID,
    show_id: uuid.UUID,
    data: bytes,
) -> ShowView:
    view = await get_show(session, user_id, show_id)  # 404 for someone else's show
    if len(data) > MAX_UPLOAD_BYTES:
        raise CoverTooLarge(f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    jpeg = await anyio.to_thread.run_sync(process_cover, data)
    key = cover_key(show_id)
    await storage.put(key, jpeg, content_type="image/jpeg")
    view.show.cover_key = key
    view.show.updated_at = func.now()  # changes the cover URL's version, busting caches
    await session.commit()
    return await get_show(session, user_id, show_id, refresh=True)


async def remove_cover(
    session: AsyncSession, storage: Storage, user_id: uuid.UUID, show_id: uuid.UUID
) -> ShowView:
    view = await get_show(session, user_id, show_id)
    if view.show.cover_key:
        await storage.delete(view.show.cover_key)
        view.show.cover_key = None
        view.show.updated_at = func.now()
        await session.commit()
    return await get_show(session, user_id, show_id, refresh=True)


async def open_cover(
    session: AsyncSession, storage: Storage, show_id: uuid.UUID
) -> tuple[ObjectInfo, AsyncIterator[bytes]]:
    """The cover of any show, for public serving (feeds and directories fetch it unauthenticated).

    Deliberately not filtered by user: show ids are unguessable and the cover is public by design.
    """
    key = await session.scalar(select(Show.cover_key).where(Show.id == show_id))
    info = await storage.head(key) if key else None
    if key is None or info is None:
        raise ShowNotFound
    return info, storage.get_stream(key)
