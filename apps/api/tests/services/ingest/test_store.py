import random
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Item, Show, Source, User
from byop.models.enums import SourceKind
from byop.services.ingest.canonical import canonical_url, content_hash
from byop.services.ingest.collect import RawItem
from byop.services.ingest.store import Candidate, StoreResult, store_items
from tests.models.factories import make_show, make_user

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
SOURCE = uuid.uuid4()


def candidate(
    title: str,
    url: str | None = None,
    summary: str = "",
    *,
    watch: bool = False,
    fingerprint: str | None = None,
) -> Candidate:
    link = url or f"https://news.example.com/{title.lower().replace(' ', '-')}"
    raw = RawItem(
        source_id=SOURCE,
        kind=SourceKind.URL if watch else SourceKind.RSS,
        title=title,
        url=link,
        summary=summary or f"Details about {title}",
        published_at=NOW,
        watch=watch,
        fingerprint=fingerprint,
    )
    canonical = canonical_url(link)
    assert canonical is not None
    return Candidate(
        raw=raw,
        canonical_url=canonical,
        content_hash=fingerprint or content_hash(raw.title, raw.summary),
        language="en",
    )


async def source_for(session: AsyncSession, show: Show) -> Source:
    source = await session.scalar(select(Source).where(Source.show_id == show.id))
    if source is None:
        source = Source(
            user_id=show.user_id,
            show_id=show.id,
            kind=SourceKind.RSS,
            value="https://f.example.com/rss",
        )
        session.add(source)
        await session.flush()
    return source


async def store(
    session: AsyncSession, show: Show, items: list[Candidate], *, now: datetime = NOW
) -> StoreResult:
    source = await source_for(session, show)  # items must point at a real source
    linked = [replace(c, raw=replace(c.raw, source_id=source.id)) for c in items]
    return await store_items(
        session, show.id, show.user_id, linked, similarity=0.55, window_days=14, now=now
    )


async def titles(session: AsyncSession, show: Show) -> set[str]:
    return set(await session.scalars(select(Item.title).where(Item.show_id == show.id)))


async def test_new_items_are_saved_with_their_details(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)

    result = await store(db_session, show, [candidate("Quantum chips arrive in data centers")])

    assert (result.inserted, result.duplicates) == (1, 0)
    item = await db_session.scalar(select(Item).where(Item.show_id == show.id))
    assert item is not None
    assert item.user_id == admin_user.id
    assert item.source_id == (await source_for(db_session, show)).id
    assert item.canonical_url == "https://news.example.com/quantum-chips-arrive-in-data-centers"
    assert item.language == "en" and item.published_at == NOW and item.ingested_at == NOW
    assert len(item.content_hash) == 64


async def test_running_it_again_is_idempotent(db_session: AsyncSession, admin_user: User) -> None:
    show = await make_show(db_session, admin_user)
    batch = [candidate("Alpha story about chips"), candidate("Beta story about robots")]

    first = await store(db_session, show, batch)
    second = await store(db_session, show, batch)

    assert (first.inserted, second.inserted) == (2, 0)
    assert second.same_url == 2
    assert await db_session.scalar(select(func.count()).select_from(Item)) == 2


async def test_duplicates_inside_one_batch_are_kept_once(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)

    result = await store(
        db_session,
        show,
        [
            candidate("Story one about planets", url="https://a.example.com/x"),
            candidate("A different headline entirely", url="https://a.example.com/x?utm_source=z"),
            candidate(
                "Story one about planets",
                url="https://b.example.com/y",
                summary="Details about Story one about planets",
            ),
        ],
    )

    assert result.inserted == 1
    assert result.same_url == 1 and result.same_content == 1


async def test_the_same_text_under_another_url_is_a_duplicate(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    await store(
        db_session,
        show,
        [candidate("Syndicated story on batteries", url="https://a.example.com/1")],
    )

    result = await store(
        db_session,
        show,
        [candidate("Syndicated story on batteries", url="https://mirror.example.org/copy")],
    )

    assert (result.inserted, result.same_content) == (0, 1)


async def test_near_identical_headlines_are_dropped(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    await store(db_session, show, [candidate("OpenAI releases new GPT model for developers")])

    result = await store(
        db_session,
        show,
        [
            candidate(
                "OpenAI releases a new GPT model for developers", url="https://other.example.com/a"
            ),
            candidate(
                "Google unveils quantum computing breakthrough", url="https://other.example.com/b"
            ),
        ],
    )

    assert (result.inserted, result.similar_title) == (1, 1)
    assert "Google unveils quantum computing breakthrough" in await titles(db_session, show)


async def test_near_identical_headlines_within_a_batch_keep_the_first(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)

    result = await store(
        db_session,
        show,
        [
            candidate("Rust 2.0 released with faster compile times", url="https://a.example.com/1"),
            candidate(
                "Rust 2.0 released with much faster compile times", url="https://b.example.com/2"
            ),
            candidate(
                "Rust 2.0 is released with faster compile times", url="https://c.example.com/3"
            ),
            candidate("Local bakery wins national award", url="https://d.example.com/4"),
        ],
    )

    assert (result.inserted, result.similar_title) == (2, 2)
    assert "Rust 2.0 released with faster compile times" in await titles(db_session, show)


async def test_old_items_do_not_count_for_fuzzy_matching(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    await store(
        db_session,
        show,
        [candidate("OpenAI releases new GPT model for developers")],
        now=NOW - timedelta(days=30),
    )

    result = await store(
        db_session,
        show,
        [
            candidate(
                "OpenAI releases a new GPT model for developers", url="https://x.example.com/n"
            )
        ],
    )

    assert (result.inserted, result.similar_title) == (1, 0)


async def test_other_shows_and_users_items_are_ignored(
    db_session: AsyncSession, admin_user: User
) -> None:
    mine = await make_show(db_session, admin_user)
    other_user = await make_user(db_session, "other@example.com")
    theirs = await make_show(db_session, other_user, slug="theirs")
    elsewhere = await make_show(db_session, admin_user, slug="elsewhere")
    same = candidate("Shared headline about solar panels", url="https://a.example.com/s")
    await store(db_session, theirs, [same])
    await store(db_session, elsewhere, [same])

    result = await store(db_session, mine, [same])

    assert result.inserted == 1


async def test_a_watched_page_is_replaced_when_its_text_changes(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    page = "https://blog.example.com/releases"
    await store(
        db_session,
        show,
        [candidate("Releases", url=page, summary="v1", watch=True, fingerprint="a" * 64)],
    )
    item = await db_session.scalar(select(Item).where(Item.show_id == show.id))
    assert item is not None
    item.used_in_episode_id = None

    unchanged = await store(
        db_session,
        show,
        [candidate("Releases", url=page, summary="v1", watch=True, fingerprint="a" * 64)],
    )
    changed = await store(
        db_session,
        show,
        [candidate("Releases (v2)", url=page, summary="v2", watch=True, fingerprint="b" * 64)],
        now=NOW + timedelta(hours=6),
    )

    assert (unchanged.inserted, unchanged.updated, unchanged.same_url) == (0, 0, 1)
    assert (changed.inserted, changed.updated) == (0, 1)
    await db_session.refresh(item)
    assert item.title == "Releases (v2)" and item.content_hash == "b" * 64
    assert item.ingested_at == NOW + timedelta(hours=6)
    assert await db_session.scalar(select(func.count()).select_from(Item)) == 1


async def test_nothing_to_store_is_fine(db_session: AsyncSession, admin_user: User) -> None:
    show = await make_show(db_session, admin_user)

    result = await store(db_session, show, [])

    assert result == StoreResult()


# --- the benchmark from the issue: 5,000 existing items, 200 new ones --------------------------


def headline(rng: random.Random) -> str:
    """Seven made-up words: unrelated headlines share (almost) no trigrams."""
    words = (
        "".join(rng.choices("abcdefghijklmnopqrstuvwxyz", k=rng.randint(5, 9))) for _ in range(7)
    )
    return " ".join(words)


async def test_ingesting_200_new_items_among_5000_existing_ones_is_fast(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    rng = random.Random(7)
    existing = [headline(rng) for _ in range(5000)]
    await db_session.execute(
        insert(Item),
        [
            {
                "id": uuid.uuid4(),
                "user_id": admin_user.id,
                "show_id": show.id,
                "canonical_url": f"https://old.example.com/{n}",
                "content_hash": f"{n:064d}",
                "title": title,
                "summary": "",
                "ingested_at": NOW - timedelta(days=2),
            }
            for n, title in enumerate(existing)
        ],
    )
    await db_session.flush()
    # Autovacuum analyses a table that has grown like this within a minute; without statistics
    # Postgres assumes the table is tiny and scans it instead of using the trigram index.
    await db_session.execute(text("ANALYZE items"))

    fresh = [headline(rng) for _ in range(200)]
    batch = [candidate(t, url=f"https://new.example.com/{n}") for n, t in enumerate(fresh)]
    # 20 of them are reworded copies of existing headlines, 10 exact repeats of existing URLs
    batch += [
        candidate(existing[n] + " today", url=f"https://copy.example.com/{n}") for n in range(20)
    ]
    batch += [candidate(f"Repeat {n} zzqx", url=f"https://old.example.com/{n}") for n in range(10)]

    started = time.perf_counter()
    result = await store(db_session, show, batch)
    elapsed = time.perf_counter() - started

    print(f"benchmark: {elapsed:.3f}s for {len(batch)} candidates against 5000 items")
    assert result.inserted == 200
    assert result.similar_title == 20 and result.same_url == 10
    assert elapsed < 5, f"took {elapsed:.2f}s"
