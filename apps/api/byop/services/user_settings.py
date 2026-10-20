"""Per-user defaults chosen in the app (`user_settings`: one row per user, made on first save)."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import ProviderConnection, UserSettings
from byop.services.provider_ref import InvalidProviderRef, ProviderRef
from byop.services.validation import FieldError, FieldValidationError


@dataclass(frozen=True)
class DiscoveryChoice:
    """The model the user picked in Settings for finding sources; both fields set, or neither."""

    provider: str | None = None
    model: str | None = None


async def _row(session: AsyncSession, user_id: uuid.UUID) -> UserSettings | None:
    return await session.scalar(select(UserSettings).where(UserSettings.user_id == user_id))


async def load_discovery_choice(session: AsyncSession, user_id: uuid.UUID) -> DiscoveryChoice:
    """Read where a `DiscoveryRequest` is built, so `choose_model` itself stays pure."""
    row = await _row(session, user_id)
    if row is None or not (row.discovery_llm_provider and row.discovery_llm_model):
        return DiscoveryChoice()
    return DiscoveryChoice(row.discovery_llm_provider, row.discovery_llm_model)


async def check_discovery_provider(
    session: AsyncSession, user_id: uuid.UUID, provider: str
) -> None:
    """A connection must exist, be enabled and be switched on for language models."""
    try:
        ref = ProviderRef.parse(provider)
    except InvalidProviderRef as exc:
        raise FieldValidationError([FieldError(("body", "provider"), str(exc))]) from exc
    if ref.connection_id is None:
        return
    record = await session.scalar(
        select(ProviderConnection).where(
            ProviderConnection.user_id == user_id, ProviderConnection.id == ref.connection_id
        )
    )
    if record is None:
        problem = "The connection does not exist"
    elif not record.enabled:
        problem = f"The connection '{record.name}' is disabled"
    elif not record.llm:
        problem = f"The connection '{record.name}' is not enabled for language models"
    else:
        return
    raise FieldValidationError([FieldError(("body", "provider"), problem)])


async def save_discovery_choice(
    session: AsyncSession, user_id: uuid.UUID, provider: str, model: str
) -> None:
    row = await _row(session, user_id)
    if row is None:
        row = UserSettings(user_id=user_id)
        session.add(row)
    row.discovery_llm_provider, row.discovery_llm_model = provider, model
    await session.commit()


async def clear_discovery_choice(session: AsyncSession, user_id: uuid.UUID) -> None:
    row = await _row(session, user_id)
    if row is not None:
        row.discovery_llm_provider = row.discovery_llm_model = None
        await session.commit()


async def request_interval(session: AsyncSession, user_id: uuid.UUID, provider: str) -> float:
    """Seconds to wait between requests to a built-in provider; 0 when none is set."""
    row = await _row(session, user_id)
    value = row.request_intervals.get(provider, 0.0) if row is not None else 0.0
    return float(value)


async def request_intervals(session: AsyncSession, user_id: uuid.UUID) -> dict[str, float]:
    row = await _row(session, user_id)
    return dict(row.request_intervals) if row is not None else {}


async def save_request_interval(
    session: AsyncSession, user_id: uuid.UUID, provider: str, seconds: float
) -> None:
    """Set a provider's wait; 0 removes it."""
    row = await _row(session, user_id)
    if row is None:
        row = UserSettings(user_id=user_id, request_intervals={})
        session.add(row)
    intervals = dict(row.request_intervals)
    if seconds > 0:
        intervals[provider] = seconds
    else:
        intervals.pop(provider, None)
    row.request_intervals = intervals  # a new object, so the change is noticed
    await session.commit()


async def discovery_choice_uses(
    session: AsyncSession, user_id: uuid.UUID, connection_id: uuid.UUID
) -> bool:
    """Whether the saved discovery model is on this connection (it counts as a use)."""
    choice = await load_discovery_choice(session, user_id)
    return choice.provider == f"conn:{connection_id}"
