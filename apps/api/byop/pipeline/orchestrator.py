"""Running a generation run stage by stage, and ending it reliably.

A run is a chain of stage tasks (`byop.tasks.pipeline`); each calls `run_stage` here. Whatever
happens, a run ends in a final status: stages finish it, `fail_run` and `finish_cancelled` end
it early, and `reap_stuck_runs` catches anything that stopped reporting.
"""

import enum
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings
from byop.models import Run, RunEvent, Show
from byop.models.enums import EventLevel, RunStatus
from byop.pipeline.context import RunContext
from byop.pipeline.errors import RunStopped, StageFailed, TransientStageError
from byop.pipeline.stages import finalize, ingest, mix, rank, script, tts
from byop.pipeline.workdir import remove_work_dir
from byop.providers.common import reset_usage_sink, set_usage_sink
from byop.services.credentials import CredentialResolver
from byop.services.langfuse import open_tracer
from byop.services.ranking import release_items
from byop.services.run_stream import announce
from byop.services.usage import UsageCollector, refresh_run_totals

log = structlog.get_logger(__name__)

ACTIVE = (RunStatus.QUEUED, RunStatus.RUNNING)


@dataclass(frozen=True)
class Stage:
    name: str
    run: Callable[[RunContext], Awaitable[None]]
    # The part of the 0-100 progress bar this stage covers.
    start: int
    end: int


STAGES: list[Stage] = [
    Stage("ingest", ingest.run, 0, 20),
    Stage("rank", rank.run, 20, 30),
    Stage("script", script.run, 30, 55),
    Stage("tts", tts.run, 55, 85),
    Stage("mix", mix.run, 85, 95),
    Stage("finalize", finalize.run, 95, 100),
]


class StageResult(enum.StrEnum):
    DONE = "done"
    SKIPPED = "skipped"  # the run had already ended
    CANCELLED = "cancelled"
    FAILED = "failed"


async def add_event(
    session: AsyncSession,
    run: Run,
    message: str,
    *,
    level: EventLevel = EventLevel.INFO,
    stage: str | None = None,
    **data: object,
) -> None:
    session.add(
        RunEvent(
            user_id=run.user_id,
            run_id=run.id,
            level=level,
            stage=stage,
            message=message,
            data=dict(data) or None,
        )
    )


async def fail_run(
    session: AsyncSession,
    run: Run,
    message: str,
    *,
    stage: str | None,
    media_root: str | None = None,
    redis: Redis | None = None,
) -> bool:
    """End an active run as failed, with its reason, give its stories back and (if the media
    root is given) delete its scratch files."""
    await session.refresh(run, ["status"])
    if run.status not in ACTIVE:
        return False  # it already ended some other way; keep that outcome
    run.status = RunStatus.FAILED
    run.error = message
    run.finished_at = datetime.now(UTC)
    await refresh_run_totals(session, run)
    await add_event(session, run, message, level=EventLevel.ERROR, stage=stage)
    await session.commit()
    await announce(redis, run.id)
    await release_items(session, run.user_id, run.id)
    if media_root:
        await remove_work_dir(media_root, run.id)
    log.warning("run_failed", run_id=str(run.id), stage=stage, error=message)
    return True


async def finish_cancelled(
    session: AsyncSession,
    run: Run,
    *,
    stage: str | None,
    media_root: str | None = None,
    redis: Redis | None = None,
) -> bool:
    await session.refresh(run, ["status"])
    if run.status not in ACTIVE:
        return False
    run.status = RunStatus.CANCELLED
    run.finished_at = datetime.now(UTC)
    await refresh_run_totals(session, run)
    await add_event(session, run, "Run cancelled", stage=stage)
    await session.commit()
    await announce(redis, run.id)
    await release_items(session, run.user_id, run.id)
    if media_root:
        await remove_work_dir(media_root, run.id)
    return True


async def _start_over(session: AsyncSession, run: Run, *, force: bool = True) -> None:
    """Reset the session after a stage ended by exception.

    Everything a stage keeps is committed as it goes, so rolling back loses nothing. Unless
    `force` is set it only happens when the session is unusable after an interrupted write
    (a rollback expires every loaded object, which is wasteful when nothing is wrong).
    """
    if force or not session.is_active:
        await session.rollback()
    await session.refresh(run)  # a rollback expires everything; async code cannot lazy-load


async def _write_usage(session: AsyncSession, collector: UsageCollector, run: Run) -> None:
    """Store what the stage's provider calls used, whatever way the stage ended."""
    user_id = run.user_id
    for attempt in (1, 2):
        try:
            await collector.flush(session, user_id)
            return
        except Exception:
            # After an interrupted write the session needs a rollback before it can be used.
            log.warning("usage_flush_failed", run_id=str(run.id), attempt=attempt, exc_info=True)
            await session.rollback()
    await session.refresh(run)


async def run_stage(
    session: AsyncSession,
    settings: Settings,
    run_id: uuid.UUID,
    stage_name: str,
    *,
    task_id: str | None = None,
    stages: Sequence[Stage] | None = None,
    redis: Redis | None = None,
) -> StageResult:
    """Run one stage of a run. A `TransientStageError` is raised for the caller to retry;
    every other outcome is recorded on the run and returned."""
    stage = next(s for s in (stages or STAGES) if s.name == stage_name)
    # System context (a worker job): the owner comes from the run itself.
    run = await session.get(Run, run_id, populate_existing=True)
    if run is None or run.status not in ACTIVE:
        return StageResult.SKIPPED  # an earlier stage failed, or the run was cancelled
    show = await session.get(Show, run.show_id)
    assert show is not None  # runs are deleted with their show

    if run.cancel_requested:
        await finish_cancelled(
            session, run, stage=stage.name, media_root=settings.media_root, redis=redis
        )
        return StageResult.CANCELLED
    if run.status is RunStatus.QUEUED:
        run.status = RunStatus.RUNNING
        run.started_at = datetime.now(UTC)
    run.stage = stage.name
    run.progress = max(run.progress, stage.start)
    if task_id:
        run.celery_task_id = task_id
    await add_event(session, run, f"Started {stage.name}", stage=stage.name)
    await session.commit()
    await announce(redis, run.id)

    context = RunContext(
        session=session,
        settings=settings,
        resolver=CredentialResolver(session, settings),
        run=run,
        show=show,
        stage=stage.name,
        progress_start=stage.start,
        progress_end=stage.end,
        redis=redis,
    )
    tracer = await open_tracer(session, context.resolver, run, show, stage.name)
    await tracer.start()
    collector = UsageCollector(listener=tracer.record)
    token = set_usage_sink(collector)
    try:
        try:
            await stage.run(context)
        finally:
            reset_usage_sink(token)
            await _write_usage(session, collector, run)
    except RunStopped:
        await _start_over(session, run, force=False)
        await finish_cancelled(
            session, run, stage=stage.name, media_root=settings.media_root, redis=redis
        )
        await tracer.finish("cancelled", "Run cancelled")
        return StageResult.CANCELLED
    except TransientStageError as exc:
        await tracer.finish("retry", f"Will retry: {exc}")
        await _start_over(session, run)
        await add_event(
            session, run, f"Temporary problem, will retry: {exc}",
            level=EventLevel.WARNING, stage=stage.name,
        )  # fmt: skip
        await session.commit()
        await announce(redis, run.id)
        raise
    except StageFailed as exc:
        message = str(exc)
        await tracer.finish("failed", message)
        await _start_over(session, run, force=False)
        await fail_run(
            session, run, message, stage=stage.name, media_root=settings.media_root, redis=redis
        )
        return StageResult.FAILED
    except Exception as exc:
        log.exception("stage_crashed", run_id=str(run_id), stage=stage.name)
        await tracer.finish("failed", f"Unexpected error in {stage.name}: {type(exc).__name__}")
        await _start_over(session, run)
        await fail_run(
            session, run, f"Unexpected error in {stage.name}: {type(exc).__name__}: {exc}",
            stage=stage.name, media_root=settings.media_root, redis=redis,
        )  # fmt: skip
        return StageResult.FAILED

    await session.refresh(run, ["status"])
    await tracer.finish("ok", last=run.status not in ACTIVE)
    if run.status in ACTIVE:  # the last stage ends the run itself; the others just advance it
        run.progress = max(run.progress, stage.end)
        await add_event(session, run, f"Finished {stage.name}", stage=stage.name)
        await session.commit()
    await announce(redis, run.id)
    return StageResult.DONE


async def reap_stuck_runs(
    session: AsyncSession,
    settings: Settings,
    *,
    now: datetime | None = None,
    redis: Redis | None = None,
) -> list[uuid.UUID]:
    """Fail runs that have not reported any progress for `RUN_TIMEOUT_MINUTES`.

    A queued run counts too: a worker that never picked it up is as bad as one that died.
    Their stories are released, so nothing stays reserved for a run that will never finish.
    """
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(minutes=settings.run_timeout_minutes)
    stuck = list(
        await session.scalars(select(Run).where(Run.status.in_(ACTIVE), Run.updated_at < cutoff))
    )
    reaped: list[uuid.UUID] = []
    for run in stuck:
        minutes = settings.run_timeout_minutes
        if await fail_run(
            session,
            run,
            f"Timed out: no progress for {minutes} minutes (the worker may have stopped)",
            stage=run.stage,
            media_root=settings.media_root,
            redis=redis,
        ):
            reaped.append(run.id)
    return reaped
