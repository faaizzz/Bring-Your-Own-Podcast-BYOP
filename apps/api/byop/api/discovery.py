import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from kombu.exceptions import OperationalError
from redis.asyncio import Redis

from byop.api.deps import CurrentUser, SessionDep, SettingsDep
from byop.api.integrations import ResolverDep
from byop.redis_client import get_redis
from byop.schemas.discovery import (
    DiscoveryJob,
    DiscoveryModel,
    DiscoveryStarted,
    DraftDiscoverRequest,
)
from byop.schemas.show import LLMProviderName
from byop.services.discovery import (
    DiscoveryRefused,
    DiscoveryRequest,
    DiscoveryUnavailable,
    describe_plan,
    plan_discovery,
    precheck_discovery,
)
from byop.services.discovery_jobs import load_job, to_response
from byop.services.shows import ShowNotFound, get_show
from byop.services.user_settings import load_discovery_choice
from byop.tasks.discovery import enqueue_discovery

router = APIRouter(prefix="/sources/discover", tags=["discovery"])


@router.post("", response_model=DiscoveryStarted, status_code=status.HTTP_202_ACCEPTED)
async def discover_for_draft(
    body: DraftDiscoverRequest,
    user: CurrentUser,
    redis: Annotated[Redis, Depends(get_redis)],
    resolver: ResolverDep,
    settings: SettingsDep,
    session: SessionDep,
) -> DiscoveryStarted:
    """Find sources for a topic before its show exists (the create wizard)."""
    chosen = await load_discovery_choice(session, user.id)
    request = DiscoveryRequest(
        user_id=user.id,
        show_id=None,
        topic=body.topic,
        language=body.language,
        llm_provider=body.llm_provider,
        llm_model=body.llm_model,
        discovery_llm_provider=chosen.provider,
        discovery_llm_model=chosen.model,
    )
    try:
        warnings = await precheck_discovery(resolver, redis, settings, request)
    except DiscoveryRefused as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    try:
        return DiscoveryStarted(
            job_id=await enqueue_discovery(redis, request, warnings), warnings=warnings
        )
    except OperationalError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The job queue is unavailable"
        ) from exc


@router.get("/model", response_model=DiscoveryModel)
async def get_discovery_model(
    user: CurrentUser,
    redis: Annotated[Redis, Depends(get_redis)],
    resolver: ResolverDep,
    settings: SettingsDep,
    session: SessionDep,
    show_id: uuid.UUID | None = None,
    llm_provider: LLMProviderName | None = None,
    llm_model: str | None = None,
) -> DiscoveryModel:
    """The model discovery would use and whether it can search the web: for a show (its own
    model), or for the wizard's draft choices. 404 when no model is set up at all."""
    if show_id is not None:
        try:
            show = (await get_show(session, user.id, show_id)).show
        except ShowNotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Show not found") from exc
        llm_provider, llm_model = show.llm_provider, show.llm_model
    chosen = await load_discovery_choice(session, user.id)
    request = DiscoveryRequest(
        user_id=user.id,
        show_id=None,
        topic="",
        llm_provider=llm_provider,
        llm_model=llm_model,
        discovery_llm_provider=chosen.provider,
        discovery_llm_model=chosen.model,
    )
    try:
        plan = await plan_discovery(resolver, redis, settings, request)
    except DiscoveryUnavailable as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return describe_plan(plan)


@router.get("/{job_id}", response_model=DiscoveryJob)
async def get_discovery(
    job_id: str, user: CurrentUser, redis: Annotated[Redis, Depends(get_redis)]
) -> DiscoveryJob:
    record = await load_job(redis, job_id)
    if record is None or record.user_id != user.id:  # unknown, expired or someone else's
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Discovery job not found")
    return to_response(job_id, record)
