"""When a show runs next, and starting the runs that are due.

`compute_next_run` is pure. `start_due_runs` is what the beat task calls every minute; it claims
due shows with `FOR UPDATE SKIP LOCKED` and advances `next_run_at` in the same transaction, so two
overlapping ticks never start the same show twice.
"""

import calendar
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Run, RunEvent, Show
from byop.models.enums import EventLevel, RunStatus, RunTrigger, ScheduleKind

log = structlog.get_logger(__name__)


def _at(day: date, at: time, zone: ZoneInfo) -> datetime:
    """The instant `at` on `day` in `zone`, in UTC.

    A time that does not exist (the clock jumps over it in spring) happens right after the jump,
    shifted by the gap; one that exists twice (the clock goes back in autumn) uses the first.
    """
    return datetime.combine(day, at.replace(tzinfo=None), tzinfo=zone).astimezone(UTC)


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        log.warning("unknown_time_zone_using_utc", timezone=name)
        return ZoneInfo("UTC")


def compute_next_run(
    kind: ScheduleKind,
    at: time | None,
    weekday: int | None,
    monthday: int | None,
    timezone: str,
    now: datetime,
) -> datetime | None:
    """The first scheduled moment strictly after `now` (UTC), or None for a manual show.

    `weekday` is 0 (Monday) to 6; `monthday` 1 to 31 and, in a shorter month, the last day. The
    time of day is wall-clock time in `timezone`, so it keeps its place across DST changes.
    """
    if kind is ScheduleKind.MANUAL or at is None:
        return None
    zone = _zone(timezone)
    today = now.astimezone(zone).date()

    days: Iterable[date]
    if kind is ScheduleKind.DAILY:
        days = (today + timedelta(days=n) for n in range(-1, 3))
    elif kind is ScheduleKind.WEEKLY:
        if weekday is None:
            return None
        days = (
            today + timedelta(days=n) for n in range(-1, 9) if (today.weekday() + n) % 7 == weekday
        )
    else:
        if monthday is None:
            return None
        days = _monthly_days(today, monthday)
    for day in days:
        candidate = _at(day, at, zone)
        if candidate > now:
            return candidate
    return None  # unreachable for a complete schedule


def _monthly_days(today: date, monthday: int) -> list[date]:
    days: list[date] = []
    year, month = today.year, today.month
    for _ in range(14):
        last = calendar.monthrange(year, month)[1]
        days.append(date(year, month, min(monthday, last)))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return days


def next_run_for(show: Show, now: datetime | None = None) -> datetime | None:
    """`compute_next_run` for a show's own schedule; None while paused or manual."""
    if show.paused:
        return None
    return compute_next_run(
        show.schedule_kind,
        show.schedule_time,
        show.schedule_weekday,
        show.schedule_monthday,
        show.timezone,
        now or datetime.now(UTC),
    )


@dataclass(frozen=True)
class DueRun:
    run_id: uuid.UUID
    show_id: uuid.UUID


async def start_due_runs(session: AsyncSession, *, now: datetime | None = None) -> list[DueRun]:
    """Queue a run for every show whose time has come; the caller then enqueues them.

    A show that was due several times (the worker was down) gets one run, not one per missed
    slot: `next_run_at` jumps to the first moment after `now`. A show that still has a run
    waiting or working skips this slot. Shows with a schedule but no `next_run_at` (created
    before scheduling existed) are given one without running.
    """
    now = now or datetime.now(UTC)
    shows = await session.scalars(
        select(Show)
        .where(
            Show.schedule_kind != ScheduleKind.MANUAL,
            Show.paused.is_(False),
            (Show.next_run_at.is_(None)) | (Show.next_run_at <= now),
        )
        .order_by(Show.next_run_at.nulls_first())
        .with_for_update(skip_locked=True)
    )
    started: list[DueRun] = []
    for show in shows:
        was_due = show.next_run_at is not None
        show.next_run_at = next_run_for(show, now)
        if not was_due:
            continue
        run = Run(
            user_id=show.user_id,
            show_id=show.id,
            trigger=RunTrigger.SCHEDULE,
            status=RunStatus.QUEUED,
        )
        try:
            async with session.begin_nested():
                session.add(run)
        except IntegrityError:
            log.info("scheduled_run_skipped_busy", show_id=str(show.id))
            continue
        session.add(
            RunEvent(
                user_id=show.user_id,
                run_id=run.id,
                level=EventLevel.INFO,
                message="Run queued",
                data={"trigger": RunTrigger.SCHEDULE.value},
            )
        )
        started.append(DueRun(run.id, show.id))
    await session.commit()
    return started
