"""Small helpers that build valid rows so tests only spell out what they care about."""

from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Episode, Item, Run, Show, Source, Speaker, UsageEvent, User
from byop.models.enums import RunTrigger, SourceKind, UsageKind


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
