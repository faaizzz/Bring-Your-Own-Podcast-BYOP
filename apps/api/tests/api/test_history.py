from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Episode, Item, Run, Show, UsageEvent, User
from byop.models.enums import EpisodeStatus, RunStatus, RunTrigger, UsageKind
from tests.models.factories import make_show, make_user

T0 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


async def add_run(
    session: AsyncSession,
    user: User,
    show: Show,
    *,
    at: datetime,
    status: RunStatus = RunStatus.SUCCEEDED,
    trigger: RunTrigger = RunTrigger.MANUAL,
    seconds: int | None = 90,
) -> Run:
    run = Run(
        user_id=user.id,
        show_id=show.id,
        trigger=trigger,
        status=status,
        created_at=at,
        started_at=at if seconds is not None else None,
        finished_at=at + timedelta(seconds=seconds) if seconds is not None else None,
    )
    session.add(run)
    await session.flush()
    return run


async def history(authed: AsyncClient, **params: object) -> dict[str, object]:
    response = await authed.get("/api/history", params={k: str(v) for k, v in params.items()})
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


def rows_of(page: dict[str, object]) -> list[dict[str, Any]]:
    items = page["items"]
    assert isinstance(items, list)
    return items


def ids(page: dict[str, object]) -> list[str]:
    return [row["id"] for row in rows_of(page)]


async def test_rows_carry_show_duration_episode_and_cost(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    run = await add_run(db_session, admin_user, show, at=T0, seconds=125)
    episode = Episode(
        user_id=admin_user.id,
        show_id=show.id,
        run_id=run.id,
        title="Oceans",
        status=EpisodeStatus.PUBLISHED,
    )
    db_session.add(episode)
    for cost in ("0.0125", "0.0050"):
        db_session.add(
            UsageEvent(
                user_id=admin_user.id,
                run_id=run.id,
                show_id=show.id,
                kind=UsageKind.LLM,
                provider="openrouter",
                cost_usd=Decimal(cost),
            )
        )
    await db_session.flush()

    page = await history(authed)

    (row,) = rows_of(page)
    assert row["id"] == str(run.id) and row["show_title"] == "Daily AI"
    assert row["trigger"] == "manual" and row["status"] == "succeeded"
    assert row["duration_s"] == 125
    assert Decimal(row["cost_usd"]) == Decimal("0.0175")
    assert row["episode_id"] == str(episode.id) and row["episode_title"] == "Oceans"
    assert row["episode_status"] == "published"
    assert page["next_cursor"] is None


async def test_unfinished_and_uncosted_runs_have_no_duration_or_cost(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    await add_run(db_session, admin_user, show, at=T0, status=RunStatus.QUEUED, seconds=None)

    (row,) = rows_of(await history(authed))

    assert row["duration_s"] is None and row["cost_usd"] is None and row["episode_id"] is None


async def test_filters_by_show_status_trigger_and_date_range(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    a = await make_show(db_session, admin_user, "a")
    b = await make_show(db_session, admin_user, "b")
    ok_a = await add_run(db_session, admin_user, a, at=T0)
    failed_a = await add_run(
        db_session, admin_user, a, at=T0 + timedelta(days=1), status=RunStatus.FAILED
    )
    sched_b = await add_run(
        db_session, admin_user, b, at=T0 + timedelta(days=2), trigger=RunTrigger.SCHEDULE
    )
    str_ids = {r: str(r.id) for r in (ok_a, failed_a, sched_b)}

    assert ids(await history(authed)) == [str_ids[sched_b], str_ids[failed_a], str_ids[ok_a]]
    assert ids(await history(authed, show_id=a.id)) == [str_ids[failed_a], str_ids[ok_a]]
    assert ids(await history(authed, status="failed")) == [str_ids[failed_a]]
    assert ids(await history(authed, trigger="schedule")) == [str_ids[sched_b]]
    assert ids(await history(authed, created_from="2026-05-02")) == [
        str_ids[sched_b],
        str_ids[failed_a],
    ]
    assert ids(await history(authed, created_to="2026-05-02")) == [
        str_ids[failed_a],
        str_ids[ok_a],
    ]
    assert ids(await history(authed, created_from="2026-05-02", created_to="2026-05-02")) == [
        str_ids[failed_a]
    ]
    assert ids(await history(authed, show_id=a.id, status="succeeded", trigger="schedule")) == []


async def test_a_thousand_runs_are_paged_in_order_without_gaps_or_repeats(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    db_session.add_all(
        Run(
            user_id=admin_user.id,
            show_id=show.id,
            trigger=RunTrigger.SCHEDULE,
            status=RunStatus.SUCCEEDED,
            # Several runs share a timestamp, so the id has to break ties.
            created_at=T0 + timedelta(minutes=n // 3),
        )
        for n in range(1000)
    )
    await db_session.flush()

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, object] = {"limit": 150}
        if cursor:
            params["cursor"] = cursor
        page = await history(authed, **params)
        seen += ids(page)
        pages += 1
        cursor = page["next_cursor"]  # type: ignore[assignment]
        if cursor is None:
            break

    assert pages == 7 and len(seen) == 1000 and len(set(seen)) == 1000
    newest = rows_of(await history(authed, limit=1))[0]["created_at"]
    assert newest.startswith("2026-05-01T17:33")  # 999 // 3 = 333 minutes after 12:00


async def test_runs_added_while_paging_do_not_shift_the_next_page(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    runs = [
        await add_run(db_session, admin_user, show, at=T0 + timedelta(hours=n)) for n in range(5)
    ]
    first = await history(authed, limit=2)
    await add_run(db_session, admin_user, show, at=T0 + timedelta(days=9))  # newest of all

    second = await history(authed, limit=2, cursor=first["next_cursor"])

    assert ids(first) == [str(runs[4].id), str(runs[3].id)]
    assert ids(second) == [str(runs[2].id), str(runs[1].id)]


async def test_an_invalid_cursor_is_422(authed: AsyncClient) -> None:
    for cursor in ("not-a-cursor", "bm9wZQ", "x"):
        response = await authed.get("/api/history", params={"cursor": cursor})
        assert response.status_code == 422, cursor


async def test_limits_are_validated(authed: AsyncClient) -> None:
    assert (await authed.get("/api/history", params={"limit": 0})).status_code == 422
    assert (await authed.get("/api/history", params={"limit": 201})).status_code == 422
    assert (await authed.get("/api/history", params={"status": "bogus"})).status_code == 422


async def test_other_users_runs_are_invisible(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    other = await make_user(db_session, "other@example.com")
    theirs = await make_show(db_session, other, "theirs")
    await add_run(db_session, other, theirs, at=T0)
    mine = await make_show(db_session, admin_user, "mine")
    run = await add_run(db_session, admin_user, mine, at=T0)

    assert ids(await history(authed)) == [str(run.id)]
    assert ids(await history(authed, show_id=theirs.id)) == []


async def test_episode_detail_lists_the_stories_it_was_made_from(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    episode = Episode(user_id=admin_user.id, show_id=show.id, title="Ep")
    db_session.add(episode)
    await db_session.flush()
    for n, used in enumerate((True, False)):
        db_session.add(
            Item(
                user_id=admin_user.id,
                show_id=show.id,
                canonical_url=f"https://example.com/story-{n}",
                content_hash=f"h{n}",
                title=f"Story {n}",
                used_in_episode_id=episode.id if used else None,
            )
        )
    await db_session.flush()

    detail = (await authed.get(f"/api/episodes/{episode.id}")).json()

    assert [(s["title"], s["url"], s["source_name"]) for s in detail["sources"]] == [
        ("Story 0", "https://example.com/story-0", None)
    ]


async def test_requires_a_session(client: AsyncClient) -> None:
    assert (await client.get("/api/history")).status_code == 401
