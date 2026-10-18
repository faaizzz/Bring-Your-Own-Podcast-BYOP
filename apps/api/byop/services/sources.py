import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Source
from byop.models.enums import SourceKind
from byop.schemas.source import SourceCreate, SourceUpdate, SourceValidation, check_value
from byop.services.feeds import FeedInvalid, FeedPreview, preview_feed
from byop.services.safe_http import FetchError, ensure_public_url
from byop.services.shows import get_show
from byop.services.validation import FieldError, FieldValidationError

VALUE_LOC = ("body", "value")


class SourceNotFound(Exception):
    pass


class SourceConflict(Exception):
    pass


def _value_error(message: str) -> FieldValidationError:
    return FieldValidationError([FieldError(VALUE_LOC, message)])


async def _check_reachable(
    kind: SourceKind, value: str, *, allow_private: bool
) -> FeedPreview | None:
    """Validate what the source points at: fetch an RSS feed, only vet the address of a page."""
    if kind is SourceKind.RSS:
        try:
            return await preview_feed(value, allow_private=allow_private)
        except FeedInvalid as exc:
            raise _value_error(str(exc)) from exc
    if kind is SourceKind.URL:
        try:
            await ensure_public_url(value, allow_private=allow_private)
        except FetchError as exc:
            raise _value_error(str(exc)) from exc
    return None


async def validate_source(kind: SourceKind, value: str, *, allow_private: bool) -> SourceValidation:
    """Try a source without saving it. Only RSS feeds are fetched."""
    if kind is not SourceKind.RSS:
        raise _value_error("Only RSS feeds can be validated by fetching")
    try:
        preview = await preview_feed(value, allow_private=allow_private)
    except FeedInvalid as exc:
        return SourceValidation(ok=False, detail=str(exc))
    return SourceValidation(
        ok=True,
        title=preview.title,
        entry_count=preview.entry_count,
        latest_titles=preview.latest_titles,
    )


async def _owned(
    session: AsyncSession, user_id: uuid.UUID, show_id: uuid.UUID, source_id: uuid.UUID
) -> Source:
    source = await session.scalar(
        select(Source).where(
            Source.id == source_id, Source.show_id == show_id, Source.user_id == user_id
        )
    )
    if source is None:
        raise SourceNotFound
    return source


async def _already_added(
    session: AsyncSession,
    show_id: uuid.UUID,
    kind: SourceKind,
    value: str,
    *,
    except_id: uuid.UUID | None = None,
) -> bool:
    query = select(Source.id).where(
        Source.show_id == show_id, Source.kind == kind, Source.value == value
    )
    if except_id is not None:
        query = query.where(Source.id != except_id)
    return await session.scalar(query) is not None


async def list_sources(
    session: AsyncSession, user_id: uuid.UUID, show_id: uuid.UUID
) -> list[Source]:
    await get_show(session, user_id, show_id)  # 404 for someone else's show
    rows = await session.scalars(
        select(Source)
        .where(Source.show_id == show_id, Source.user_id == user_id)
        .order_by(Source.created_at, Source.id)
    )
    return list(rows)


async def create_source(
    session: AsyncSession,
    user_id: uuid.UUID,
    show_id: uuid.UUID,
    data: SourceCreate,
    *,
    allow_private: bool,
) -> Source:
    await get_show(session, user_id, show_id)
    if await _already_added(session, show_id, data.kind, data.value):
        raise SourceConflict("This source is already added to the show")
    preview = await _check_reachable(data.kind, data.value, allow_private=allow_private)

    source = Source(
        user_id=user_id,
        show_id=show_id,
        kind=data.kind,
        value=data.value,
        # A feed names itself when the user does not.
        name=data.name or (preview.title if preview else None),
        origin=data.origin,
        enabled=data.enabled,
    )
    try:
        async with session.begin_nested():
            session.add(source)
    except IntegrityError as exc:  # added concurrently
        raise SourceConflict("This source is already added to the show") from exc
    await session.commit()
    return source


async def update_source(
    session: AsyncSession,
    user_id: uuid.UUID,
    show_id: uuid.UUID,
    source_id: uuid.UUID,
    data: SourceUpdate,
    *,
    allow_private: bool,
) -> Source:
    await get_show(session, user_id, show_id)
    source = await _owned(session, user_id, show_id, source_id)
    changes = data.model_dump(exclude_unset=True)

    new_value = changes.get("value")
    if new_value is not None and new_value != source.value:
        # Re-apply the kind's rules to the new value (the schema cannot: it does not know the kind).
        try:
            check_value(source.kind, new_value)
        except ValueError as exc:
            raise _value_error(str(exc)) from exc
        if await _already_added(session, show_id, source.kind, new_value, except_id=source.id):
            raise SourceConflict("This source is already added to the show")
        await _check_reachable(source.kind, new_value, allow_private=allow_private)
        source.value = new_value
        # It is a different place now: forget how the old one behaved.
        source.last_fetched_at = None
        source.last_error = None
    if "name" in changes:
        source.name = changes["name"] or None
    if changes.get("enabled") is not None:
        source.enabled = changes["enabled"]

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise SourceConflict("This source is already added to the show") from exc
    return source


async def delete_source(
    session: AsyncSession, user_id: uuid.UUID, show_id: uuid.UUID, source_id: uuid.UUID
) -> None:
    await get_show(session, user_id, show_id)
    source = await _owned(session, user_id, show_id, source_id)
    await session.delete(source)
    await session.commit()
