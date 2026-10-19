"""Discovery runs in the worker; its progress and result live in Redis for an hour."""

import json
import uuid

from pydantic import BaseModel
from redis.asyncio import Redis

from byop.schemas.discovery import DiscoveredSource, DiscoveryJob, DiscoveryStatus

JOB_TTL_SECONDS = 3600


class JobRecord(BaseModel):
    user_id: uuid.UUID
    show_id: uuid.UUID | None
    status: DiscoveryStatus = DiscoveryStatus.QUEUED
    candidates: list[DiscoveredSource] = []
    error: str | None = None
    warnings: list[str] = []


def _key(job_id: str) -> str:
    return f"discovery:{job_id}"


async def create_job(
    redis: Redis,
    user_id: uuid.UUID,
    show_id: uuid.UUID | None,
    warnings: list[str] | None = None,
) -> str:
    job_id = uuid.uuid4().hex
    record = JobRecord(user_id=user_id, show_id=show_id, warnings=warnings or [])
    await redis.set(_key(job_id), record.model_dump_json(), ex=JOB_TTL_SECONDS)
    return job_id


async def load_job(redis: Redis, job_id: str) -> JobRecord | None:
    raw = await redis.get(_key(job_id))
    if raw is None:
        return None
    return JobRecord.model_validate(json.loads(raw))


async def save_job(redis: Redis, job_id: str, record: JobRecord) -> None:
    await redis.set(_key(job_id), record.model_dump_json(), ex=JOB_TTL_SECONDS)


def to_response(job_id: str, record: JobRecord) -> DiscoveryJob:
    return DiscoveryJob(
        job_id=job_id,
        status=record.status,
        show_id=record.show_id,
        candidates=record.candidates,
        error=record.error,
        warnings=record.warnings,
    )
