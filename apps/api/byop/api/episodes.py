import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from kombu.exceptions import OperationalError

from byop.api.audio_response import audio_response
from byop.api.deps import CurrentUser, SessionDep, StorageDep
from byop.models import Episode, Run
from byop.models.enums import EpisodeStatus
from byop.pipeline.orchestrator import fail_run
from byop.schemas.episode import (
    EpisodeResponse,
    EpisodeRunInfo,
    EpisodeSource,
    EpisodeSummary,
    EpisodeUpdate,
)
from byop.services import episodes as service
from byop.services.script_revision import audio_revision_of, revision_of
from byop.services.shows import ShowNotFound
from byop.services.validation import FieldValidationError, error_detail
from byop.storage import StorageError
from byop.tasks.pipeline import RESYNTH_STAGES, enqueue_run

router = APIRouter(prefix="/episodes", tags=["episodes"])
show_router = APIRouter(prefix="/shows/{show_id}/episodes", tags=["episodes"])

NotFound = HTTPException(status.HTTP_404_NOT_FOUND, "Episode not found")
StorageDown = HTTPException(status.HTTP_502_BAD_GATEWAY, "Media storage is unavailable")


def _run_info(run: Run | None) -> EpisodeRunInfo | None:
    if run is None:
        return None
    return EpisodeRunInfo(
        id=run.id,
        trigger=run.trigger,
        status=run.status,
        stage=run.stage,
        progress=run.progress,
        error=run.error,
    )


def _summary(episode: Episode, run: Run | None) -> EpisodeSummary:
    return EpisodeSummary(
        id=episode.id,
        show_id=episode.show_id,
        title=episode.title,
        status=episode.status,
        published_at=episode.published_at,
        duration_s=episode.duration_s,
        size_bytes=episode.size_bytes,
        created_at=episode.created_at,
        run=_run_info(run),
    )


async def _detail(session: SessionDep, user_id: uuid.UUID, episode: Episode) -> EpisodeResponse:
    run = (await service.runs_of(session, user_id, [episode])).get(
        episode.run_id or uuid.UUID(int=0)
    )
    names = await service.speaker_names(session, user_id, episode.show_id)
    sources = await service.sources_of(session, user_id, episode.id)
    return EpisodeResponse(
        **_summary(episode, run).model_dump(),
        description=episode.description,
        segments=service.segments_of(episode),
        speakers=names,
        revision=revision_of(episode.script),
        audio_revision=audio_revision_of(episode.script),
        audio_current=service.is_audio_current(episode),
        audio_url=(
            f"/api/episodes/{episode.id}/audio?v={int(episode.updated_at.timestamp())}"
            if episode.audio_key
            else None
        ),
        sources=[
            EpisodeSource(
                id=item.id,
                title=item.title,
                url=item.canonical_url,
                source_name=name,
                published_at=item.published_at,
            )
            for item, name in sources
        ],
        updated_at=episode.updated_at,
    )


@show_router.get("", response_model=list[EpisodeSummary])
async def list_episodes(
    show_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    episode_status: Annotated[EpisodeStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[EpisodeSummary]:
    try:
        rows = await service.list_episodes(
            session, user.id, show_id, status=episode_status, limit=limit, offset=offset
        )
    except ShowNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Show not found") from exc
    by_run = await service.runs_of(session, user.id, rows)
    return [_summary(e, by_run.get(e.run_id or uuid.UUID(int=0))) for e in rows]


@router.get("/{episode_id}", response_model=EpisodeResponse)
async def get_episode(
    episode_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> EpisodeResponse:
    try:
        return await _detail(
            session, user.id, await service.get_episode(session, user.id, episode_id)
        )
    except service.EpisodeNotFound as exc:
        raise NotFound from exc


@router.patch("/{episode_id}", response_model=EpisodeResponse)
async def update_episode(
    episode_id: uuid.UUID, body: EpisodeUpdate, user: CurrentUser, session: SessionDep
) -> EpisodeResponse:
    """Edit the title, description and script of a draft (published episodes are fixed)."""
    try:
        episode = await service.update_episode(session, user.id, episode_id, body)
    except service.EpisodeNotFound as exc:
        raise NotFound from exc
    except service.EpisodeConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except FieldValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail=error_detail(exc.errors)
        ) from exc
    return await _detail(session, user.id, episode)


@router.post(
    "/{episode_id}/resynthesize",
    response_model=EpisodeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resynthesize(
    episode_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> EpisodeResponse:
    """Voice and mix the current script again; progress shows on the episode's run."""
    try:
        run = await service.resynthesize(session, user.id, episode_id)
    except service.EpisodeNotFound as exc:
        raise NotFound from exc
    except service.EpisodeConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    try:
        run.celery_task_id = enqueue_run(run.id, RESYNTH_STAGES)[:64]
        await session.commit()
    except OperationalError as exc:
        await fail_run(session, run, "The job queue is unavailable", stage=None)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The job queue is unavailable"
        ) from exc
    return await _detail(session, user.id, await service.get_episode(session, user.id, episode_id))


@router.post("/{episode_id}/approve", response_model=EpisodeResponse)
async def approve_episode(
    episode_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> EpisodeResponse:
    """Publish the draft. Refused while its script differs from the audio that was made."""
    try:
        episode = await service.approve(session, user.id, episode_id)
    except service.EpisodeNotFound as exc:
        raise NotFound from exc
    except service.EpisodeConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _detail(session, user.id, episode)


@router.post("/{episode_id}/reject", response_model=EpisodeResponse)
async def reject_episode(
    episode_id: uuid.UUID, user: CurrentUser, session: SessionDep, storage: StorageDep
) -> EpisodeResponse:
    """Discard the draft; its stories can go into a later episode."""
    try:
        episode = await service.reject(session, storage, user.id, episode_id)
    except service.EpisodeNotFound as exc:
        raise NotFound from exc
    except service.EpisodeConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except StorageError as exc:
        raise StorageDown from exc
    return await _detail(session, user.id, episode)


@router.get("/{episode_id}/audio", response_class=StreamingResponse)
async def episode_audio(
    episode_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    """The episode's MP3 for the review player; supports `Range` so it can seek."""
    try:
        episode = await service.get_episode(session, user.id, episode_id)
    except service.EpisodeNotFound as exc:
        raise NotFound from exc
    if episode.audio_key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The episode has no audio yet")
    return await audio_response(
        storage, episode.audio_key, range_header, cache_control="private, no-cache"
    )
