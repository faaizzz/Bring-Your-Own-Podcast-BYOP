import asyncio
from collections.abc import Callable

import structlog
from kombu.exceptions import OperationalError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Run
from byop.pipeline.orchestrator import fail_run
from byop.services.schedule import start_due_runs
from byop.tasks.pipeline import enqueue_run
from byop.tasks.runtime import task_deps
from byop.worker import celery_app

log = structlog.get_logger(__name__)


async def tick(
    session: AsyncSession,
    redis: Redis | None = None,
    enqueue: Callable[..., str] = enqueue_run,
) -> int:
    """Start the runs that are due; returns how many were queued."""
    queued = 0
    for due in await start_due_runs(session):
        run = await session.get(Run, due.run_id)
        if run is None:
            continue
        try:
            run.celery_task_id = enqueue(due.run_id)[:64]
            await session.commit()
            queued += 1
            log.info("scheduled_run_queued", show_id=str(due.show_id), run_id=str(due.run_id))
        except OperationalError:
            # Do not leave a run queued that nothing will ever pick up.
            await fail_run(session, run, "The job queue is unavailable", stage=None, redis=redis)
    return queued


@celery_app.task(name="byop.schedule_tick")
def schedule_tick_task() -> int:
    """Every minute (beat): queue a run for each show whose scheduled time has come."""

    async def run() -> int:
        async with task_deps() as (session, redis, _settings):
            return await tick(session, redis)

    return asyncio.run(run())
