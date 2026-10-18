import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from kombu.exceptions import OperationalError

from byop.api.deps import CurrentUser, RedisDep, SessionDep, SettingsDep
from byop.api.integrations import ResolverDep
from byop.celery_control import revoke_quietly
from byop.config import Settings
from byop.models import Run
from byop.models.enums import CredentialProvider, RunStatus
from byop.pipeline.orchestrator import fail_run
from byop.schemas.costs import UsageLine
from byop.schemas.run import RunDetail, RunEventResponse, RunResponse
from byop.services import costs as costs_service
from byop.services import runs as service
from byop.services.credentials import (
    CredentialDecryptionError,
    CredentialResolver,
    ProviderNotConfigured,
)
from byop.services.langfuse import trace_url
from byop.services.run_stream import announce, stream_run
from byop.services.shows import ShowNotFound
from byop.tasks.pipeline import enqueue_run

router = APIRouter(prefix="/runs", tags=["runs"])
show_router = APIRouter(prefix="/shows/{show_id}/runs", tags=["runs"])


def _response(run: Run, episode_id: uuid.UUID | None = None) -> RunResponse:
    return RunResponse(
        id=run.id,
        show_id=run.show_id,
        trigger=run.trigger,
        status=run.status,
        stage=run.stage,
        progress=run.progress,
        error=run.error,
        cancel_requested=run.cancel_requested,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        episode_id=episode_id,
    )


async def _trace_url(
    resolver: CredentialResolver, settings: Settings, user_id: uuid.UUID, run: Run
) -> str | None:
    if run.trace_id is None:
        return None
    try:
        config = await resolver.get(user_id, CredentialProvider.LANGFUSE)
    except (ProviderNotConfigured, CredentialDecryptionError):
        return None
    return trace_url(config, settings.langfuse_public_url, run.trace_id)


async def _detail(
    session: SessionDep,
    user_id: uuid.UUID,
    run: Run,
    resolver: CredentialResolver,
    settings: Settings,
) -> RunDetail:
    episode_id = (await service.episode_ids(session, user_id, [run.id])).get(run.id)
    return RunDetail(
        **_response(run, episode_id).model_dump(),
        trace_url=await _trace_url(resolver, settings, user_id, run),
        events=[
            RunEventResponse(
                id=e.id, ts=e.ts, level=e.level, stage=e.stage, message=e.message, data=e.data
            )
            for e in run.events
        ],
    )


@show_router.post("", response_model=RunResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_run(show_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> RunResponse:
    """Queue a generation run for the show (one at a time per show)."""
    try:
        run = await service.create_run(session, user.id, show_id)
    except ShowNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Show not found") from exc
    except service.RunConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    try:
        run.celery_task_id = enqueue_run(run.id)[:64]
        await session.commit()
    except OperationalError as exc:
        # Do not leave a run queued that nothing will ever pick up.
        await fail_run(session, run, "The job queue is unavailable", stage=None)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The job queue is unavailable"
        ) from exc
    return _response(run)


@router.get("", response_model=list[RunResponse])
async def list_runs(
    user: CurrentUser,
    session: SessionDep,
    show_id: uuid.UUID | None = None,
    run_status: Annotated[RunStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RunResponse]:
    runs = await service.list_runs(
        session, user.id, show_id=show_id, status=run_status, limit=limit, offset=offset
    )
    episodes = await service.episode_ids(session, user.id, [r.id for r in runs])
    return [_response(r, episodes.get(r.id)) for r in runs]


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    resolver: ResolverDep,
    settings: SettingsDep,
) -> RunDetail:
    try:
        run = await service.get_run(session, user.id, run_id)
        return await _detail(session, user.id, run, resolver, settings)
    except service.RunNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found") from exc


@router.get("/{run_id}/usage", response_model=list[UsageLine])
async def run_usage(run_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> list[UsageLine]:
    """What the run's model and voice calls used and cost, by stage and model."""
    try:
        await service.get_run(session, user.id, run_id)
    except service.RunNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found") from exc
    return await costs_service.run_usage(session, user.id, run_id)


@router.post("/{run_id}/cancel", response_model=RunDetail)
async def cancel_run(
    run_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    redis: RedisDep,
    resolver: ResolverDep,
    settings: SettingsDep,
) -> RunDetail:
    """Stop a run: at once if it is still queued, otherwise at its next step."""
    try:
        run = await service.request_cancel(session, user.id, run_id)
    except service.RunNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found") from exc
    except service.RunConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    revoke_quietly(run.celery_task_id)
    await announce(redis, run.id)
    return await _detail(session, user.id, run, resolver, settings)


@router.get("/{run_id}/stream", response_class=StreamingResponse)
async def stream(
    run_id: uuid.UUID, user: CurrentUser, session: SessionDep, redis: RedisDep
) -> StreamingResponse:
    """Server-Sent Events: the run's state and log as it happens (`snapshot`, `update`, `done`).

    The database is the source of truth, so a client that reconnects after a network drop
    receives the current state again (EventSource does this by itself).
    """
    try:
        await service.get_run(session, user.id, run_id)  # 404 before the stream starts
    except service.RunNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found") from exc
    return StreamingResponse(
        stream_run(session, redis, user.id, run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # nginx: do not hold the events back
        },
    )
