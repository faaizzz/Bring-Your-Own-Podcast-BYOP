"""Small helpers that build valid rows so tests only spell out what they care about."""

from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import (
    Episode,
    Item,
    ProviderConnection,
    Run,
    Show,
    Source,
    Speaker,
    UsageEvent,
    User,
)
from byop.models.enums import RunTrigger, SourceKind, UsageKind
from byop.services.credentials import CredentialResolver
from tests.helpers import make_settings


async def make_user(session: AsyncSession, email: str = "admin@example.com") -> User:
    user = User(email=email, password_hash="not-a-real-hash", is_admin=True)
    session.add(user)
    await session.flush()
    return user


async def make_show(session: AsyncSession, user: User, slug: str = "daily-ai") -> Show:
    show = Show(user_id=user.id, title="Daily AI", slug=slug, topic="AI news")
    session.add(show)
    await session.flush()
    return show


async def make_full_show(session: AsyncSession, user: User) -> Show:
    """A show with one row in every child table."""
    show = await make_show(session, user)
    session.add(
        Speaker(
            user_id=user.id,
            show_id=show.id,
            position=0,
            name="Ada",
            tts_provider="openai",
            voice_id="alloy",
        )
    )
    source = Source(
        user_id=user.id, show_id=show.id, kind=SourceKind.RSS, value="https://e.com/rss"
    )
    run = Run(user_id=user.id, show_id=show.id, trigger=RunTrigger.MANUAL)
    session.add_all([source, run])
    await session.flush()
    episode = Episode(user_id=user.id, show_id=show.id, run_id=run.id, title="Ep 1")
    session.add(episode)
    await session.flush()
    session.add_all(
        [
            Item(
                user_id=user.id,
                show_id=show.id,
                source_id=source.id,
                canonical_url="https://e.com/1",
                content_hash="h1",
                title="Story one",
                used_in_episode_id=episode.id,
            ),
            UsageEvent(
                user_id=user.id,
                show_id=show.id,
                run_id=run.id,
                kind=UsageKind.LLM,
                provider="openrouter",
                model="m",
            ),
        ]
    )
    await session.flush()
    return show


async def make_connection(
    session: AsyncSession,
    user: User,
    name: str = "Local",
    *,
    base_url: str = "http://llm.local/v1",
    api_key: str | None = None,
    headers: Mapping[str, str] | None = None,
    llm: bool = True,
    tts: bool = False,
    web_search: bool = False,
    enabled: bool = True,
) -> ProviderConnection:
    """An OpenAI-compatible connection, sealed with the test secret key."""
    sealed = CredentialResolver(session, make_settings()).seal_connection(api_key, headers or {})
    record = ProviderConnection(
        user_id=user.id,
        name=name,
        base_url=base_url,
        secret_encrypted=sealed,
        llm=llm,
        tts=tts,
        web_search=web_search,
        enabled=enabled,
    )
    session.add(record)
    await session.flush()
    return record
