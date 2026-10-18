from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from kombu.exceptions import OperationalError
from redis.asyncio import Redis

from byop.api.deps import CurrentUser
from byop.redis_client import get_redis
from byop.schemas.discovery import DiscoveryJob, DiscoveryStarted, DraftDiscoverRequest
from byop.services.discovery import DiscoveryRequest
from byop.services.discovery_jobs import load_job, to_response
from byop.tasks.discovery import enqueue_discovery

router = APIRouter(prefix="/sources/discover", tags=["discovery"])


@router.post("", response_model=DiscoveryStarted, status_code=status.HTTP_202_ACCEPTED)
async def discover_for_draft(
    body: DraftDiscoverRequest,
    user: CurrentUser,
    redis: Annotated[Redis, Depends(get_redis)],
) -> DiscoveryStarted:
    """Find sources for a topic before its show exists (the create wizard)."""
    request = DiscoveryRequest(
        user_id=user.id,
        show_id=None,
        topic=body.topic,
        language=body.language,
        llm_provider=body.llm_provider,
        llm_model=body.llm_model,
    )
    try:
        return DiscoveryStarted(job_id=await enqueue_discovery(redis, request))
    except OperationalError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The job queue is unavailable"
        ) from exc


@router.get("/{job_id}", response_model=DiscoveryJob)
async def get_discovery(
    job_id: str, user: CurrentUser, redis: Annotated[Redis, Depends(get_redis)]
) -> DiscoveryJob:
    record = await load_job(redis, job_id)
    if record is None or record.user_id != user.id:  # unknown, expired or someone else's
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Discovery job not found")
    return to_response(job_id, record)
