import asyncio
import uuid
from datetime import UTC, datetime, time

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from byop.models import Run, Show, User
from byop.models.enums import RunStatus, RunTrigger, ScheduleKind
from byop.services.schedule import compute_next_run, start_due_runs
from tests.models.factories import make_show

D, W, M, MAN = (
    ScheduleKind.DAILY,
    ScheduleKind.WEEKLY,
    ScheduleKind.MONTHLY,
    ScheduleKind.MANUAL,
)


def utc(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


# kind, at, weekday, monthday, timezone, now, expected
CASES: list[
    tuple[ScheduleKind, time | None, int | None, int | None, str, datetime, datetime | None]
] = [
    # manual shows never run by themselves
    (MAN, None, None, None, "UTC", utc(2026, 1, 1), None),
    # daily: later today, then tomorrow; "strictly after" means now itself does not count
    (D, time(9), None, None, "UTC", utc(2026, 5, 1, 8, 0), utc(2026, 5, 1, 9, 0)),
    (D, time(9), None, None, "UTC", utc(2026, 5, 1, 9, 0), utc(2026, 5, 2, 9, 0)),
    (D, time(9), None, None, "UTC", utc(2026, 5, 1, 9, 0, 1), utc(2026, 5, 2, 9, 0)),
    (D, time(0, 0), None, None, "UTC", utc(2026, 12, 31, 12), utc(2027, 1, 1, 0, 0)),
    # the local date, not the UTC date, decides what "today" is
    (D, time(9), None, None, "Asia/Tokyo", utc(2025, 12, 31, 23, 0), utc(2026, 1, 1, 0, 0)),
    (D, time(9), None, None, "Asia/Tokyo", utc(2026, 1, 1, 0, 30), utc(2026, 1, 2, 0, 0)),
    (
        D,
        time(23, 30),
        None,
        None,
        "America/Los_Angeles",
        utc(2026, 1, 1, 6),
        utc(2026, 1, 1, 7, 30),
    ),
    # DST: wall-clock time keeps its place (Berlin springs forward on 2026-03-29)
    (D, time(8), None, None, "Europe/Berlin", utc(2026, 3, 28, 12), utc(2026, 3, 29, 6, 0)),
    (D, time(8), None, None, "Europe/Berlin", utc(2026, 3, 29, 6, 0), utc(2026, 3, 30, 6, 0)),
    # ...and falls back on 2026-10-25
    (D, time(8), None, None, "Europe/Berlin", utc(2026, 10, 24, 12), utc(2026, 10, 25, 7, 0)),
    # a time skipped by spring-forward (02:30 does not exist in New York on 2026-03-08) runs
    # right after the jump, shifted by the gap
    (D, time(2, 30), None, None, "America/New_York", utc(2026, 3, 7, 12), utc(2026, 3, 8, 7, 30)),
    (
        D,
        time(2, 30),
        None,
        None,
        "America/New_York",
        utc(2026, 3, 8, 7, 30),
        utc(2026, 3, 9, 6, 30),
    ),
    # a time that happens twice in autumn (01:30 on 2026-11-01) uses the first one
    (
        D,
        time(1, 30),
        None,
        None,
        "America/New_York",
        utc(2026, 10, 31, 12),
        utc(2026, 11, 1, 5, 30),
    ),
    (
        D,
        time(1, 30),
        None,
        None,
        "America/New_York",
        utc(2026, 11, 1, 5, 30),
        utc(2026, 11, 2, 6, 30),
    ),
    # a half-hour zone
    (D, time(6, 0), None, None, "Asia/Kolkata", utc(2026, 6, 1, 0, 0), utc(2026, 6, 1, 0, 30)),
    # weekly: 2026-10-18 is a Sunday
    (W, time(9), 0, None, "UTC", utc(2026, 10, 18, 16), utc(2026, 10, 19, 9, 0)),
    (W, time(9), 0, None, "UTC", utc(2026, 10, 19, 8), utc(2026, 10, 19, 9, 0)),
    (W, time(9), 0, None, "UTC", utc(2026, 10, 19, 9), utc(2026, 10, 26, 9, 0)),
    (W, time(9), 6, None, "UTC", utc(2026, 10, 18, 8), utc(2026, 10, 18, 9, 0)),
    (W, time(9), 6, None, "UTC", utc(2026, 10, 18, 10), utc(2026, 10, 25, 9, 0)),
    (W, time(23, 0), 4, None, "Asia/Tokyo", utc(2026, 1, 1, 0), utc(2026, 1, 2, 14, 0)),
    # weekly across the autumn change: Monday 09:00 Berlin
    (W, time(9), 0, None, "Europe/Berlin", utc(2026, 10, 19, 12), utc(2026, 10, 26, 8, 0)),
    # monthly: a day beyond the month's end means its last day
    (M, time(10), None, 31, "UTC", utc(2026, 1, 31, 11), utc(2026, 2, 28, 10, 0)),
    (M, time(10), None, 31, "UTC", utc(2026, 2, 28, 10), utc(2026, 3, 31, 10, 0)),
    (M, time(10), None, 31, "UTC", utc(2026, 3, 31, 11), utc(2026, 4, 30, 10, 0)),
    (M, time(10), None, 30, "UTC", utc(2026, 1, 30, 11), utc(2026, 2, 28, 10, 0)),
    (M, time(10), None, 29, "UTC", utc(2026, 1, 30), utc(2026, 2, 28, 10, 0)),
    # Feb 29 exists in a leap year
    (M, time(10), None, 29, "UTC", utc(2028, 1, 30), utc(2028, 2, 29, 10, 0)),
    (M, time(10), None, 31, "UTC", utc(2028, 2, 1), utc(2028, 2, 29, 10, 0)),
    (M, time(10), None, 29, "UTC", utc(2028, 2, 29, 10), utc(2028, 3, 29, 10, 0)),
    # year rollover and a day that has not come yet this month
    (M, time(10), None, 15, "UTC", utc(2026, 12, 20), utc(2027, 1, 15, 10, 0)),
    (M, time(10), None, 15, "UTC", utc(2026, 12, 1), utc(2026, 12, 15, 10, 0)),
    (M, time(10), None, 1, "Pacific/Auckland", utc(2026, 6, 30, 10), utc(2026, 6, 30, 22, 0)),
]


@pytest.mark.parametrize(("kind", "at", "weekday", "monthday", "zone", "now", "expected"), CASES)
def test_next_run(
    kind: ScheduleKind,
    at: time | None,
    weekday: int | None,
    monthday: int | None,
    zone: str,
    now: datetime,
    expected: datetime | None,
) -> None:
    assert compute_next_run(kind, at, weekday, monthday, zone, now) == expected


def test_next_run_is_always_after_now_and_within_a_period() -> None:
    now = utc(2026, 3, 8, 6, 59)
    for zone in ("America/New_York", "Europe/Berlin", "Australia/Lord_Howe", "UTC"):
        for hour in range(24):
            for kind, weekday, monthday, days in (
                (D, None, None, 2),
                (W, 3, None, 8),
                (M, None, 31, 32),
            ):
                got = compute_next_run(kind, time(hour, 30), weekday, monthday, zone, now)
                assert got is not None and got > now
                assert (got - now).days <= days


def test_an_unknown_time_zone_falls_back_to_utc() -> None:
    assert compute_next_run(D, time(9), None, None, "Mars/Olympus", utc(2026, 1, 1)) == utc(
        2026, 1, 1, 9
    )


def test_an_incomplete_schedule_has_no_next_run() -> None:
    assert compute_next_run(W, time(9), None, None, "UTC", utc(2026, 1, 1)) is None
    assert compute_next_run(M, time(9), None, None, "UTC", utc(2026, 1, 1)) is None
    assert compute_next_run(D, None, None, None, "UTC", utc(2026, 1, 1)) is None


# --- starting due runs ---------------------------------------------------------------------------


async def scheduled_show(
    session: AsyncSession, user: User, *, slug: str = "daily-ai", **values: object
) -> Show:
    show = await make_show(session, user, slug)
    show.schedule_kind = D
    show.schedule_time = time(9)
    show.timezone = "UTC"
    show.next_run_at = utc(2026, 5, 1, 9)
    for name, value in values.items():
        setattr(show, name, value)
    await session.flush()
    return show


async def runs_of(session: AsyncSession, show: Show) -> list[Run]:
    return list(await session.scalars(select(Run).where(Run.show_id == show.id)))


async def test_a_due_show_gets_one_scheduled_run_and_moves_on(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await scheduled_show(db_session, admin_user)

    started = await start_due_runs(db_session, now=utc(2026, 5, 1, 9, 0, 30))

    assert [s.show_id for s in started] == [show.id]
    (run,) = await runs_of(db_session, show)
    assert run.trigger is RunTrigger.SCHEDULE and run.status is RunStatus.QUEUED
    assert run.id == started[0].run_id
    await db_session.refresh(show)
    assert show.next_run_at == utc(2026, 5, 2, 9)


async def test_a_show_that_is_not_due_is_left_alone(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await scheduled_show(db_session, admin_user)

    assert await start_due_runs(db_session, now=utc(2026, 5, 1, 8, 59)) == []
    assert await runs_of(db_session, show) == []
    await db_session.refresh(show)
    assert show.next_run_at == utc(2026, 5, 1, 9)


async def test_downtime_makes_one_catch_up_run_not_one_per_missed_slot(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await scheduled_show(db_session, admin_user, next_run_at=utc(2026, 5, 1, 9))

    started = await start_due_runs(db_session, now=utc(2026, 5, 5, 12))

    assert len(started) == 1
    await db_session.refresh(show)
    assert show.next_run_at == utc(2026, 5, 6, 9)
    assert await start_due_runs(db_session, now=utc(2026, 5, 5, 12, 1)) == []


async def test_paused_and_manual_shows_do_not_run(
    db_session: AsyncSession, admin_user: User
) -> None:
    paused = await scheduled_show(db_session, admin_user, slug="paused", paused=True)
    manual = await scheduled_show(
        db_session, admin_user, slug="manual", schedule_kind=MAN, schedule_time=None
    )

    assert await start_due_runs(db_session, now=utc(2026, 5, 2)) == []
    assert await runs_of(db_session, paused) == [] and await runs_of(db_session, manual) == []


async def test_a_show_with_a_run_in_progress_skips_the_slot_but_keeps_its_schedule(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await scheduled_show(db_session, admin_user)
    db_session.add(
        Run(
            user_id=admin_user.id,
            show_id=show.id,
            trigger=RunTrigger.MANUAL,
            status=RunStatus.RUNNING,
        )
    )
    await db_session.flush()

    assert await start_due_runs(db_session, now=utc(2026, 5, 1, 9, 1)) == []

    assert len(await runs_of(db_session, show)) == 1
    await db_session.refresh(show)
    assert show.next_run_at == utc(2026, 5, 2, 9)


async def test_a_show_waiting_for_review_does_not_block_the_next_run(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await scheduled_show(db_session, admin_user)
    db_session.add(
        Run(
            user_id=admin_user.id,
            show_id=show.id,
            trigger=RunTrigger.SCHEDULE,
            status=RunStatus.AWAITING_REVIEW,
        )
    )
    await db_session.flush()

    assert len(await start_due_runs(db_session, now=utc(2026, 5, 1, 9, 1))) == 1


async def test_a_scheduled_show_without_a_next_run_is_given_one_and_not_run(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await scheduled_show(db_session, admin_user, next_run_at=None)

    assert await start_due_runs(db_session, now=utc(2026, 5, 1, 12)) == []

    await db_session.refresh(show)
    assert show.next_run_at == utc(2026, 5, 2, 9)
    assert await runs_of(db_session, show) == []


async def test_two_overlapping_ticks_never_start_a_show_twice(engine: AsyncEngine) -> None:
    """Real, separate connections: while one tick holds a show, the other leaves it alone."""
    now = utc(2026, 5, 1, 9, 5)
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        user = User(email=f"sched-{uuid.uuid4().hex}@example.com", password_hash="x", is_admin=True)
        setup.add(user)
        await setup.flush()
        show = await make_show(setup, user, f"sched-{uuid.uuid4().hex[:8]}")
        show.schedule_kind, show.schedule_time = D, time(9)
        show.next_run_at = utc(2026, 5, 1, 9)
        await setup.commit()
        user_id, show_id = user.id, show.id
    try:
        async with (
            AsyncSession(engine, expire_on_commit=False) as first,
            AsyncSession(engine, expire_on_commit=False) as second,
        ):
            # The first tick has claimed the show but not committed yet.
            claimed = await first.scalars(
                select(Show)
                .where(Show.id == show_id, Show.next_run_at <= now)
                .with_for_update(skip_locked=True)
            )
            assert [s.id for s in claimed] == [show_id]
            assert await start_due_runs(second, now=now) == []
            await first.rollback()

            # Run back to back and concurrently: exactly one run results.
            results = await asyncio.gather(
                start_due_runs(first, now=now), start_due_runs(second, now=now)
            )
        assert sum(len(r) for r in results) == 1
        async with AsyncSession(engine) as check:
            count = await check.scalar(
                select(func.count()).select_from(Run).where(Run.show_id == show_id)
            )
        assert count == 1
    finally:
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(delete(User).where(User.id == user_id))
            await cleanup.commit()
