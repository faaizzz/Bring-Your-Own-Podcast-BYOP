import asyncio
import uuid

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings
from byop.providers.llm import LLMError
from byop.schemas.discovery import DiscoveryStatus
from byop.services.credentials import CredentialResolver
from byop.services.discovery import DiscoveryRequest, DiscoveryUnavailable, discover_sources
from byop.services.discovery_jobs import create_job, load_job, save_job
from byop.tasks.runtime import task_deps
from byop.worker import celery_app

log = structlog.get_logger(__name__)


async def run_discovery_job(
    job_id: str,
    request: DiscoveryRequest,
    *,
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
) -> None:
    """Run one discovery and record the outcome on the job; never raises."""
    record = await load_job(redis, job_id)
    if record is None:  # expired before the worker got to it
        return
    record.status = DiscoveryStatus.RUNNING
    await save_job(redis, job_id, record)
    try:
        candidates = await discover_sources(
            session, CredentialResolver(session, settings), settings, request
        )
    except DiscoveryUnavailable as exc:
        record.status, record.error = DiscoveryStatus.FAILED, str(exc)
    except LLMError as exc:
        record.status = DiscoveryStatus.FAILED
        if exc.status_code in (401, 403):
            record.error = (
                "The model provider rejected the API key. Check it under Settings › Integrations."
            )
        else:
            record.error = f"The language model failed: {exc}"
    except Exception:
        # The job is the only channel back to the user, so it must always end in a final state.
        log.exception("discovery_failed", job_id=job_id)
        record.status, record.error = DiscoveryStatus.FAILED, "Discovery failed unexpectedly."
    else:
        record.status, record.candidates = DiscoveryStatus.DONE, candidates
    await save_job(redis, job_id, record)


async def _run(job_id: str, request: DiscoveryRequest) -> None:
    async with task_deps() as (session, redis, settings):
        await run_discovery_job(job_id, request, session=session, redis=redis, settings=settings)


@celery_app.task(name="byop.discover_sources")
def discover_sources_task(
    job_id: str,
    user_id: str,
    show_id: str | None,
    topic: str,
    language: str | None,
    llm_provider: str | None,
    llm_model: str | None,
) -> None:
    request = DiscoveryRequest(
        user_id=uuid.UUID(user_id),
        show_id=uuid.UUID(show_id) if show_id else None,
        topic=topic,
        language=language,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    asyncio.run(_run(job_id, request))


async def enqueue_discovery(redis: Redis, request: DiscoveryRequest) -> str:
    """Create the job record and hand the work to the worker; returns the job id."""
    job_id = await create_job(redis, request.user_id, request.show_id)
    discover_sources_task.delay(
        job_id,
        str(request.user_id),
        str(request.show_id) if request.show_id else None,
        request.topic,
        request.language,
        request.llm_provider,
        request.llm_model,
    )
    return job_id
