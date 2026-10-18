import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from redis.asyncio import Redis
from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings
from byop.models import Episode, Run, Show
from byop.models.enums import CredentialProvider, RunStatus
from byop.providers.llm import UnsupportedLLMProvider, get_llm
from byop.schemas.show import ShowCreate, ShowUpdate, schedule_problem
from byop.services.credentials import (
    CredentialDecryptionError,
    CredentialResolver,
    ProviderNotConfigured,
)
from byop.services.models import list_models_cached
from byop.services.storage import Storage, show_prefix

log = structlog.get_logger(__name__)

MAX_SLUG_LENGTH = 100


class ShowNotFound(Exception):
    pass


class ShowInvalid(Exception):
    """The request is well-formed but not acceptable (maps to 422)."""


class ShowConflict(Exception):
    """The request clashes with existing data (maps to 409)."""


@dataclass(frozen=True)
class ShowView:
    """A show plus the figures the API reports next to it."""

    show: Show
    episode_count: int
    last_run_status: RunStatus | None
    slug_locked: bool
    warnings: list[str] = field(default_factory=list)


def slugify(title: str) -> str:
    """Lowercase ASCII words joined by hyphens; 'show' when nothing usable is left."""
    ascii_text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[: MAX_SLUG_LENGTH - 8].strip("-") or "show"


async def _unique_slug(session: AsyncSession, base: str) -> str:
    """`base`, or `base-2`, `base-3`... Slugs are unique across the instance (feed URLs)."""
    taken = set(await session.scalars(select(Show.slug).where(Show.slug.like(f"{base}%"))))
    if base not in taken:
        return base
    number = 2
    while f"{base}-{number}" in taken:
        number += 1
    return f"{base}-{number}"


def _stats_query(user_id: uuid.UUID) -> Any:
    episode_count = (
        select(func.count())
        .select_from(Episode)
        .where(Episode.show_id == Show.id)
        .correlate(Show)
        .scalar_subquery()
    )
    last_run_status = (
        select(Run.status)
        .where(Run.show_id == Show.id)
        .order_by(Run.created_at.desc())
        .limit(1)
        .correlate(Show)
        .scalar_subquery()
    )
    slug_locked = exists().where(Episode.show_id == Show.id, Episode.published_at.is_not(None))
    return select(Show, episode_count, last_run_status, slug_locked).where(Show.user_id == user_id)


def _view(row: Any, warnings: list[str] | None = None) -> ShowView:
    show, count, last_status, locked = row
    return ShowView(show, int(count or 0), last_status, bool(locked), warnings or [])


async def list_shows(session: AsyncSession, user_id: uuid.UUID) -> list[ShowView]:
    rows = await session.execute(_stats_query(user_id).order_by(Show.created_at.desc()))
    return [_view(row) for row in rows.all()]


async def get_show(
    session: AsyncSession, user_id: uuid.UUID, show_id: uuid.UUID, *, refresh: bool = False
) -> ShowView:
    query = _stats_query(user_id).where(Show.id == show_id)
    if refresh:
        query = query.execution_options(populate_existing=True)
    row = (await session.execute(query)).first()
    if row is None:
        raise ShowNotFound
    return _view(row)


async def verify_model(
    resolver: CredentialResolver,
    redis: Redis,
    user_id: uuid.UUID,
    provider: str,
    model: str,
) -> list[str]:
    """Reject a model the provider does not offer; warn when that cannot be checked."""
    name = CredentialProvider(provider)
    unverified = f"Could not verify model '{model}' with {provider}"
    try:
        config = await resolver.get(user_id, name)
        llm = get_llm(name, config)
    except (ProviderNotConfigured, CredentialDecryptionError, UnsupportedLLMProvider):
        return [f"{unverified}: the provider is not configured."]
    try:
        try:
            models = await list_models_cached(redis, llm, config)
        finally:
            await llm.aclose()
    except Exception:  # a provider outage must not block editing a show
        log.warning("model_verification_failed", provider=provider, exc_info=True)
        return [f"{unverified}: its model list is unavailable."]
    if not models:
        return [f"{unverified}: the provider lists no models."]
    if model not in {m.id for m in models}:
        raise ShowInvalid(f"Model '{model}' is not offered by {provider}")
    return []


def _check_model_pair(provider: str | None, model: str | None) -> None:
    if (provider is None) != (model is None):
        raise ShowInvalid("llm_provider and llm_model must be set together")


async def create_show(
    session: AsyncSession,
    resolver: CredentialResolver,
    redis: Redis,
    settings: Settings,
    user_id: uuid.UUID,
    data: ShowCreate,
) -> ShowView:
    values = data.model_dump(exclude={"slug"})
    warnings: list[str] = []

    # Instance defaults fill what the request left open; only the user's own choice is verified.
    if values["llm_provider"] is None and values["llm_model"] is None:
        values["llm_provider"] = settings.default_llm_provider
        values["llm_model"] = settings.default_llm_model if settings.default_llm_provider else None
    else:
        _check_model_pair(values["llm_provider"], values["llm_model"])
        warnings += await verify_model(
            resolver, redis, user_id, values["llm_provider"], values["llm_model"]
        )
    if values["style"] is None:
        values["style"] = settings.default_show_style

    if data.slug is not None:
        if await session.scalar(select(Show.id).where(Show.slug == data.slug)):
            raise ShowConflict(f"The slug '{data.slug}' is already taken")
        slug = data.slug
    else:
        slug = await _unique_slug(session, slugify(data.title))

    show = Show(user_id=user_id, slug=slug, **values)
    try:
        async with session.begin_nested():
            session.add(show)
    except IntegrityError as exc:  # lost a race for the slug
        raise ShowConflict(f"The slug '{slug}' is already taken") from exc
    await session.commit()
    view = await get_show(session, user_id, show.id, refresh=True)
    return ShowView(view.show, view.episode_count, view.last_run_status, False, warnings)


async def update_show(
    session: AsyncSession,
    resolver: CredentialResolver,
    redis: Redis,
    user_id: uuid.UUID,
    show_id: uuid.UUID,
    data: ShowUpdate,
) -> ShowView:
    current = await get_show(session, user_id, show_id)
    show = current.show
    changes = data.model_dump(exclude_unset=True)
    warnings: list[str] = []

    new_slug = changes.pop("slug", None)
    if new_slug is not None and new_slug != show.slug:
        if current.slug_locked:
            raise ShowConflict(
                "The slug cannot change after an episode has been published; "
                "it is part of the feed URL"
            )
        if await session.scalar(select(Show.id).where(Show.slug == new_slug)):
            raise ShowConflict(f"The slug '{new_slug}' is already taken")
        changes["slug"] = new_slug

    if "llm_provider" in changes or "llm_model" in changes:
        provider = changes.get("llm_provider", show.llm_provider)
        model = changes.get("llm_model", show.llm_model)
        _check_model_pair(provider, model)
        if provider is not None and model is not None:
            warnings += await verify_model(resolver, redis, user_id, provider, model)

    problem = schedule_problem(
        changes.get("schedule_kind", show.schedule_kind),
        changes.get("schedule_time", show.schedule_time),
        changes.get("schedule_weekday", show.schedule_weekday),
        changes.get("schedule_monthday", show.schedule_monthday),
    )
    if problem:
        raise ShowInvalid(problem)

    for name, value in changes.items():
        setattr(show, name, value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ShowConflict("The slug is already taken") from exc
    view = await get_show(session, user_id, show_id, refresh=True)
    return ShowView(view.show, view.episode_count, view.last_run_status, view.slug_locked, warnings)


async def delete_show(
    session: AsyncSession, storage: Storage, user_id: uuid.UUID, show_id: uuid.UUID
) -> None:
    """Delete the show (the database cascades to its children), then its media files."""
    show = (await get_show(session, user_id, show_id)).show
    await session.delete(show)
    await session.commit()
    try:
        await storage.delete_prefix(show_prefix(show_id))
    except OSError:
        # The rows are gone; leftover files are harmless and must not fail the request.
        log.warning("show_media_cleanup_failed", show_id=str(show_id), exc_info=True)
