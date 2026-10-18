"""The generation history: runs across shows, with their episode and cost, newest first.

Paged with a keyset cursor on `(created_at, id)`, so a page costs the same however far back it
is and rows added meanwhile never shift it.
"""

import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Episode, Run, Show, UsageEvent
from byop.models.enums import EpisodeStatus, RunStatus, RunTrigger

MAX_LIMIT = 200


class InvalidCursor(ValueError):
    pass


@dataclass(frozen=True)
class HistoryFilters:
    show_id: uuid.UUID | None = None
    status: RunStatus | None = None
    trigger: RunTrigger | None = None
    # Whole days in UTC, both ends included.
    created_from: date | None = None
    created_to: date | None = None


@dataclass(frozen=True)
class HistoryRow:
    run: Run
    show_title: str
    episode_id: uuid.UUID | None
    episode_title: str | None
    episode_status: EpisodeStatus | None
    cost_usd: Decimal | None


@dataclass(frozen=True)
class HistoryPage:
    rows: list[HistoryRow]
    next_cursor: str | None


def encode_cursor(created_at: datetime, run_id: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}|{run_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        stamp, _, ident = raw.partition("|")
        return datetime.fromisoformat(stamp), uuid.UUID(ident)
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise InvalidCursor("Invalid cursor") from exc


async def list_history(
    session: AsyncSession,
    user_id: uuid.UUID,
    filters: HistoryFilters,
    *,
    cursor: str | None = None,
    limit: int = 50,
) -> HistoryPage:
    limit = max(1, min(limit, MAX_LIMIT))
    cost = (
        select(func.sum(UsageEvent.cost_usd))
        .where(UsageEvent.run_id == Run.id)
        .correlate(Run)
        .scalar_subquery()
    )
    query = (
        select(Run, Show.title, Episode.id, Episode.title, Episode.status, cost)
        .join(Show, Show.id == Run.show_id)
        .outerjoin(Episode, Episode.run_id == Run.id)
        .where(Run.user_id == user_id)
    )
    if filters.show_id is not None:
        query = query.where(Run.show_id == filters.show_id)
    if filters.status is not None:
        query = query.where(Run.status == filters.status)
    if filters.trigger is not None:
        query = query.where(Run.trigger == filters.trigger)
    if filters.created_from is not None:
        query = query.where(Run.created_at >= datetime.combine(filters.created_from, time.min, UTC))
    if filters.created_to is not None:
        end = datetime.combine(filters.created_to + timedelta(days=1), time.min, UTC)
        query = query.where(Run.created_at < end)
    if cursor is not None:
        query = query.where(tuple_(Run.created_at, Run.id) < tuple_(*decode_cursor(cursor)))

    result = await session.execute(
        query.order_by(Run.created_at.desc(), Run.id.desc()).limit(limit + 1)
    )
    fetched = result.all()
    rows = [
        HistoryRow(run, show_title, episode_id, episode_title, episode_status, total)
        for run, show_title, episode_id, episode_title, episode_status, total in fetched[:limit]
    ]
    more = len(fetched) > limit
    next_cursor = encode_cursor(rows[-1].run.created_at, rows[-1].run.id) if more else None
    return HistoryPage(rows, next_cursor)
