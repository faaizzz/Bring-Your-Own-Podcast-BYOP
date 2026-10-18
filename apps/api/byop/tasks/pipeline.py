import asyncio
import uuid

import structlog
from celery import Task, chain

from byop.models.enums import EventLevel
from byop.pipeline.errors import TransientStageError
from byop.pipeline.orchestrator import STAGES, fail_run, reap_stuck_runs, run_stage
from byop.tasks.runtime import task_deps
from byop.worker import celery_app

log = structlog.get_logger(__name__)

RETRY_BACKOFF_S = 5
MAX_RETRY_DELAY_S = 120


async def _run_stage(run_id: uuid.UUID, stage: str, task_id: str | None) -> str:
    async with task_deps() as (session, _redis, settings):
        return (await run_stage(session, settings, run_id, stage, task_id=task_id)).value


async def _give_up(run_id: uuid.UUID, stage: str, message: str) -> None:
    from byop.models import Run

    async with task_deps() as (session, _redis, _settings):
        run = await session.get(Run, run_id)
        if run is not None:
            await fail_run(session, run, message, stage=stage)


@celery_app.task(bind=True, name="byop.run_stage")
def run_stage_task(self: Task, run_id: str, stage: str) -> str:  # type: ignore[type-arg]
    """One stage of a run. Transient errors are retried with backoff; everything else is
    recorded on the run by `run_stage`, after which the later stages find the run ended and
    do nothing."""
    from byop.config import get_settings

    max_retries = get_settings().run_stage_max_retries
    try:
        return asyncio.run(_run_stage(uuid.UUID(run_id), stage, self.request.id))
    except TransientStageError as exc:
        if self.request.retries >= max_retries:
            asyncio.run(
                _give_up(
                    uuid.UUID(run_id),
                    stage,
                    f"{stage} kept failing after {max_retries} retries: {exc}",
                )
            )
            return "failed"
        delay = min(RETRY_BACKOFF_S * 2**self.request.retries, MAX_RETRY_DELAY_S)
        raise self.retry(exc=exc, countdown=delay, max_retries=max_retries) from exc


@celery_app.task(name="byop.reap_runs")
def reap_runs_task() -> list[str]:
    """Fail runs that stopped reporting progress (periodic, see `worker.py`)."""

    async def reap() -> list[str]:
        async with task_deps() as (session, _redis, settings):
            return [str(i) for i in await reap_stuck_runs(session, settings)]

    reaped = asyncio.run(reap())
    if reaped:
        log.warning("runs_reaped", run_ids=reaped, level=EventLevel.WARNING.value)
    return reaped


def build_chain(run_id: uuid.UUID):  # type: ignore[no-untyped-def]  # celery's chain is untyped
    """ingest -> rank -> script -> tts -> mix -> finalize, each as an independent task."""
    return chain(*(run_stage_task.si(str(run_id), stage.name) for stage in STAGES))


def enqueue_run(run_id: uuid.UUID) -> str:
    """Start the chain; returns the id of its last task."""
    result = build_chain(run_id).apply_async()
    return str(result.id)
