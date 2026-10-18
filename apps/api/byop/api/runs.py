import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from kombu.exceptions import OperationalError

from byop.api.deps import CurrentUser, SessionDep
from byop.celery_control import revoke_quietly
from byop.models import Run
from byop.models.enums import RunStatus
from byop.pipeline.orchestrator import fail_run
from byop.schemas.run import RunDetail, RunEventResponse, RunResponse
from byop.services import runs as service
from byop.services.shows import ShowNotFound
from byop.tasks.pipeline import enqueue_run

router = APIRouter(prefix="/runs", tags=["runs"])
show_router = APIRouter(prefix="/shows/{show_id}/runs", tags=["runs"])


def _response(run: Run) -> RunResponse:
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
    )


def _detail(run: Run) -> RunDetail:
    return RunDetail(
        **_response(run).model_dump(),
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
    return [_response(r) for r in runs]


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(run_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> RunDetail:
    try:
        return _detail(await service.get_run(session, user.id, run_id))
    except service.RunNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found") from exc


@router.post("/{run_id}/cancel", response_model=RunDetail)
async def cancel_run(run_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> RunDetail:
    """Stop a run: at once if it is still queued, otherwise at its next step."""
    try:
        run = await service.request_cancel(session, user.id, run_id)
    except service.RunNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found") from exc
    except service.RunConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    revoke_quietly(run.celery_task_id)
    return _detail(run)
