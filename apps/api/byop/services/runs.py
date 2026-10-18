import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from byop.models import Episode, Run
from byop.models.enums import EventLevel, RunStatus, RunTrigger
from byop.pipeline.orchestrator import ACTIVE, add_event
from byop.services.shows import get_show


class RunNotFound(Exception):
    pass


class RunConflict(Exception):
    """The request clashes with the run's state (one is already active; it already ended)."""


async def create_run(
    session: AsyncSession,
    user_id: uuid.UUID,
    show_id: uuid.UUID,
    trigger: RunTrigger = RunTrigger.MANUAL,
) -> Run:
    """Queue a run for the show. The database allows only one waiting or working run per show."""
    await get_show(session, user_id, show_id)  # 404 for someone else's show
    run = Run(user_id=user_id, show_id=show_id, trigger=trigger, status=RunStatus.QUEUED)
    try:
        async with session.begin_nested():
            session.add(run)
    except IntegrityError as exc:
        raise RunConflict("A run is already in progress for this show") from exc
    await add_event(session, run, "Run queued", level=EventLevel.INFO, trigger=trigger.value)
    await session.commit()
    return run


async def list_runs(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    show_id: uuid.UUID | None = None,
    status: RunStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Run]:
    query = select(Run).where(Run.user_id == user_id)
    if show_id is not None:
        query = query.where(Run.show_id == show_id)
    if status is not None:
        query = query.where(Run.status == status)
    rows = await session.scalars(
        query.order_by(Run.created_at.desc(), Run.id).limit(limit).offset(offset)
    )
    return list(rows)


async def episode_ids(
    session: AsyncSession, user_id: uuid.UUID, run_ids: list[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """The draft episode each run produced (or is re-voicing), where there is one."""
    if not run_ids:
        return {}
    rows = await session.execute(
        select(Episode.run_id, Episode.id).where(
            Episode.run_id.in_(run_ids), Episode.user_id == user_id
        )
    )
    return {run_id: episode_id for run_id, episode_id in rows if run_id is not None}


async def get_run(session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> Run:
    """The run with its log, oldest event first."""
    run = await session.scalar(
        select(Run)
        .where(Run.id == run_id, Run.user_id == user_id)
        .options(selectinload(Run.events))
        .execution_options(populate_existing=True)
    )
    if run is None:
        raise RunNotFound
    return run


async def request_cancel(session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> Run:
    """Ask a run to stop.

    A run that has not started is cancelled on the spot; a running one is flagged and stops at
    its next checkpoint (so it may take a moment to show as cancelled).
    """
    run = await get_run(session, user_id, run_id)
    if run.status not in ACTIVE:
        raise RunConflict(f"The run already ended ({run.status.value})")
    # Atomic: if a worker starts the run at the same moment, the flag below still stops it.
    queued = await session.execute(
        update(Run)
        .where(Run.id == run.id, Run.status == RunStatus.QUEUED)
        .values(status=RunStatus.CANCELLED, cancel_requested=True, finished_at=datetime.now(UTC))
        .returning(Run.id)
    )
    if queued.first() is not None:
        await add_event(session, run, "Run cancelled before it started")
    else:
        await session.execute(update(Run).where(Run.id == run.id).values(cancel_requested=True))
        await add_event(session, run, "Cancellation requested; stopping at the next step")
    await session.commit()
    return await get_run(session, user_id, run_id)
