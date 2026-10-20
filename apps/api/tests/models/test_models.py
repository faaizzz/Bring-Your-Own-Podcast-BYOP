import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import (
    Episode,
    Item,
    PriceOverride,
    ProviderCredential,
    Run,
    Show,
    Source,
    Speaker,
    Style,
    UsageEvent,
    User,
)
from byop.models.enums import (
    CostSource,
    CredentialProvider,
    EpisodeStatus,
    RunStatus,
    RunTrigger,
    ScheduleKind,
    ShowStyle,
    SourceKind,
    SourceOrigin,
    UsageKind,
)
from tests.models.factories import make_full_show, make_show, make_user


async def count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


async def test_defaults_and_timestamps(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    show = await make_show(db_session, user)
    await db_session.refresh(show)

    assert isinstance(show.id, uuid.UUID)
    assert show.style is ShowStyle.NEWS_BRIEFING
    assert show.schedule_kind is ScheduleKind.MANUAL
    assert (show.language, show.timezone, show.target_minutes) == ("en", "UTC", 10)
    assert show.paused is False and show.auto_publish is False
    assert show.created_at.tzinfo is not None
    assert show.updated_at.tzinfo is not None


async def test_updated_at_moves_on_update(db_session: AsyncSession) -> None:
    show = await make_show(db_session, await make_user(db_session))
    await db_session.refresh(show)
    before = show.updated_at

    # now() is the transaction start time, so push the stored value into the past first.
    await db_session.execute(
        text("UPDATE shows SET updated_at = now() - interval '1 day' WHERE id = :i"), {"i": show.id}
    )
    show.title = "Renamed"
    await db_session.flush()
    await db_session.refresh(show)

    assert show.updated_at >= before


async def test_deleting_a_show_cascades_to_every_child(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    show = await make_full_show(db_session, user)
    other = await make_show(db_session, user, slug="other")
    db_session.add(
        Speaker(
            user_id=user.id,
            show_id=other.id,
            position=0,
            name="Bo",
            tts_provider="openai",
            voice_id="echo",
        )
    )
    await db_session.flush()

    await db_session.delete(show)
    await db_session.flush()
    db_session.expire_all()

    assert await count(db_session, Speaker) == 1  # only the other show's speaker remains
    for model in (Source, Item, Run, Episode):
        assert await count(db_session, model) == 0, model.__name__
    assert await count(db_session, Show) == 1


async def test_usage_events_outlive_their_show(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    show = await make_full_show(db_session, user)

    await db_session.delete(show)
    await db_session.flush()
    db_session.expire_all()

    event = (await db_session.scalars(select(UsageEvent))).one()
    assert event.show_id is None and event.run_id is None


async def test_deleting_a_user_removes_everything_they_own(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await make_full_show(db_session, user)
    db_session.add(
        ProviderCredential(
            user_id=user.id, provider=CredentialProvider.OPENAI, secret_encrypted="token"
        )
    )
    await db_session.flush()

    await db_session.delete(user)
    await db_session.flush()
    db_session.expire_all()

    for model in (Show, Speaker, Source, Item, Run, Episode, UsageEvent, ProviderCredential, User):
        assert await count(db_session, model) == 0, model.__name__


async def test_deleting_an_episode_keeps_the_item(db_session: AsyncSession) -> None:
    show = await make_full_show(db_session, await make_user(db_session))
    episode = (await db_session.scalars(select(Episode).where(Episode.show_id == show.id))).one()

    await db_session.delete(episode)
    await db_session.flush()
    db_session.expire_all()

    item = (await db_session.scalars(select(Item))).one()
    assert item.used_in_episode_id is None


async def test_slug_is_unique_across_the_instance(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await make_show(db_session, user, slug="same")
    with pytest.raises(IntegrityError):
        await make_show(db_session, user, slug="same")


async def test_item_url_is_unique_per_show_only(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    a = await make_show(db_session, user, slug="a")
    b = await make_show(db_session, user, slug="b")
    for show in (a, b):  # the same URL in two shows is fine
        db_session.add(
            Item(
                user_id=user.id,
                show_id=show.id,
                canonical_url="https://x/1",
                content_hash="h",
                title="t",
            )
        )
    await db_session.flush()

    db_session.add(
        Item(
            user_id=user.id,
            show_id=a.id,
            canonical_url="https://x/1",
            content_hash="h2",
            title="dup",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_speaker_positions_are_unique_per_show(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    show = await make_show(db_session, user)
    for name in ("A", "B"):
        db_session.add(
            Speaker(
                user_id=user.id,
                show_id=show.id,
                position=0,
                name=name,
                tts_provider="openai",
                voice_id="v",
            )
        )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_money_is_exact_decimal(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    event = UsageEvent(
        user_id=user.id,
        kind=UsageKind.TTS,
        provider="openai",
        cost_usd=Decimal("0.000123"),
        cost_source=CostSource.PRICE_TABLE,
    )
    db_session.add(event)
    await db_session.flush()
    await db_session.refresh(event)

    assert event.cost_usd == Decimal("0.000123")
    assert isinstance(event.cost_usd, Decimal)


async def test_jsonb_round_trip(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    show = await make_show(db_session, user)
    script = {"turns": [{"speaker": "Ada", "text": "Hello"}]}
    episode = Episode(user_id=user.id, show_id=show.id, title="E", script=script)
    speaker = Speaker(
        user_id=user.id,
        show_id=show.id,
        position=0,
        name="Ada",
        tts_provider="openai",
        voice_id="v",
        voice_params={"speed": 1.1},
    )
    db_session.add_all([episode, speaker])
    await db_session.flush()
    episode_id, speaker_id = episode.id, speaker.id
    db_session.expire_all()

    assert (await db_session.get(Episode, episode_id)).script == script  # type: ignore[union-attr]
    assert (await db_session.get(Speaker, speaker_id)).voice_params == {"speed": 1.1}  # type: ignore[union-attr]


async def test_timestamps_are_timezone_aware(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    show = await make_show(db_session, user)
    show.next_run_at = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
    await db_session.flush()
    show_id = show.id
    db_session.expire_all()

    loaded = await db_session.get(Show, show_id)
    assert loaded is not None and loaded.next_run_at == datetime(2026, 1, 1, 8, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("table", "column", "bad"),
    [
        ("shows", "style", "podcast"),
        ("shows", "schedule_kind", "hourly"),
        ("sources", "kind", "ftp"),
        ("sources", "origin", "robot"),
        ("runs", "trigger", "cron"),
        ("runs", "status", "done"),
        ("episodes", "status", "live"),
        ("usage_events", "kind", "image"),
        ("usage_events", "cost_source", "guess"),
        ("price_overrides", "kind", "image"),
        ("provider_credentials", "provider", "acme"),
    ],
)
async def test_enum_columns_reject_unknown_values(
    db_session: AsyncSession, table: str, column: str, bad: str
) -> None:
    """The database itself refuses values outside the enums, whatever the ORM allows."""
    user = await make_user(db_session)
    show = await make_show(db_session, user)
    # Valid baseline rows via the ORM, then corrupt one column with raw SQL.
    row_id = {
        "shows": show.id,
    }.get(table)
    if row_id is None:
        factory: dict[str, object] = {
            "sources": Source(
                user_id=user.id,
                show_id=show.id,
                kind=SourceKind.RSS,
                value="v",
                origin=SourceOrigin.USER,
            ),
            "runs": Run(
                user_id=user.id, show_id=show.id, trigger=RunTrigger.MANUAL, status=RunStatus.QUEUED
            ),
            "episodes": Episode(
                user_id=user.id, show_id=show.id, title="t", status=EpisodeStatus.DRAFT
            ),
            "usage_events": UsageEvent(user_id=user.id, kind=UsageKind.LLM, provider="p"),
            "price_overrides": PriceOverride(user_id=user.id, kind=UsageKind.TTS, name="openai"),
            "provider_credentials": ProviderCredential(
                user_id=user.id, provider=CredentialProvider.OPENAI, secret_encrypted="x"
            ),
        }
        obj = factory[table]
        db_session.add(obj)
        await db_session.flush()
        row_id = obj.id  # type: ignore[attr-defined]

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(f"UPDATE {table} SET {column} = :v WHERE id = :i"), {"v": bad, "i": row_id}
        )


async def test_check_constraints_on_numeric_ranges(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    db_session.add(Show(user_id=user.id, title="t", slug="s", topic="x", schedule_weekday=7))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_trigram_index_accelerates_title_similarity(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    show = await make_show(db_session, user)
    db_session.add(
        Item(
            user_id=user.id,
            show_id=show.id,
            canonical_url="https://x/1",
            content_hash="h",
            title="OpenAI releases a new model",
        )
    )
    await db_session.flush()

    rows = (
        await db_session.execute(
            text("SELECT title FROM items WHERE title % :q"), {"q": "OpenAI released new model"}
        )
    ).all()

    assert rows == [("OpenAI releases a new model",)]


async def test_a_style_in_use_cannot_be_deleted_from_the_database(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    show = await make_show(db_session, user)
    style = Style(user_id=user.id, name="Mine", instructions="Talk.")
    db_session.add(style)
    await db_session.flush()
    show.custom_style_id = style.id
    await db_session.flush()

    with pytest.raises(IntegrityError, match="fk_shows_custom_style_id_styles"):
        async with db_session.begin_nested():
            await db_session.delete(style)


async def test_deleting_a_user_also_removes_their_styles_even_when_shows_use_them(
    db_session: AsyncSession,
) -> None:
    user = await make_user(db_session)
    show = await make_show(db_session, user)
    style = Style(user_id=user.id, name="Mine", instructions="Talk.")
    db_session.add(style)
    await db_session.flush()
    show.custom_style_id = style.id
    await db_session.flush()

    await db_session.delete(user)
    await db_session.flush()
    db_session.expire_all()

    assert await count(db_session, Style) == 0 and await count(db_session, Show) == 0


async def test_a_style_name_is_unique_per_user(db_session: AsyncSession) -> None:
    first, second = await make_user(db_session), await make_user(db_session, "b@example.com")
    db_session.add_all(
        [
            Style(user_id=first.id, name="Same", instructions="x"),
            Style(user_id=second.id, name="Same", instructions="x"),  # another user: fine
        ]
    )
    await db_session.flush()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(Style(user_id=first.id, name="Same", instructions="y"))
            await db_session.flush()
