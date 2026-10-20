import asyncio
import uuid
from dataclasses import replace

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings
from byop.providers.llm import LLMError
from byop.schemas.discovery import DiscoveryStatus
from byop.services.credentials import CredentialResolver
from byop.services.discovery import (
    DiscoveryRequest,
    DiscoveryUnavailable,
    choose_model,
    discover_sources,
)
from byop.services.discovery_errors import explain_llm_error, explain_unexpected
from byop.services.discovery_jobs import create_job, load_job, save_job
from byop.services.user_settings import load_discovery_choice
from byop.services.web_search import PROVIDER_LABELS
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
    # The Settings choice is read when the job runs, so a change made while it waited counts.
    chosen = await load_discovery_choice(session, request.user_id)
    request = replace(
        request, discovery_llm_provider=chosen.provider, discovery_llm_model=chosen.model
    )
    record.status = DiscoveryStatus.RUNNING
    await save_job(redis, job_id, record)
    try:
        candidates = await discover_sources(
            session, CredentialResolver(session, settings), settings, request, redis
        )
    except DiscoveryUnavailable as exc:
        record.status, record.error = DiscoveryStatus.FAILED, str(exc)
    except LLMError as exc:
        record.status = DiscoveryStatus.FAILED
        record.error = explain_llm_error(
            exc,
            provider=await _provider_label(session, settings, request),
            model=_model_of(settings, request),
        )
    except Exception as exc:
        # The job is the only channel back to the user, so it must always end in a final state.
        log.exception("discovery_failed", job_id=job_id)
        record.status, record.error = DiscoveryStatus.FAILED, explain_unexpected(exc)
    else:
        record.status, record.candidates = DiscoveryStatus.DONE, candidates
    await save_job(redis, job_id, record)


def _model_of(settings: Settings, request: DiscoveryRequest) -> str:
    try:
        return choose_model(settings, request)[1]
    except DiscoveryUnavailable:
        return "the model"


async def _provider_label(
    session: AsyncSession, settings: Settings, request: DiscoveryRequest
) -> str:
    """A name for the provider in messages: the connection's name, or the built-in's."""
    try:
        ref = choose_model(settings, request)[0]
        config = await CredentialResolver(session, settings).get_ref(request.user_id, ref)
    except Exception:  # the label is only for the message
        return "The model provider"
    return config.label or PROVIDER_LABELS.get(config.provider, config.provider.value)


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


async def enqueue_discovery(
    redis: Redis, request: DiscoveryRequest, warnings: list[str] | None = None
) -> str:
    """Create the job record and hand the work to the worker; returns the job id."""
    job_id = await create_job(redis, request.user_id, request.show_id, warnings)
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
