import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis

from byop.api.deps import CurrentUser, SessionDep, SettingsDep, StorageDep
from byop.api.integrations import ResolverDep
from byop.redis_client import get_redis
from byop.schemas.show import ShowCreate, ShowResponse, ShowUpdate
from byop.services import shows as service
from byop.services.shows import ShowView

router = APIRouter(prefix="/shows", tags=["shows"])

RedisDep = Annotated[Redis, Depends(get_redis)]


def response_for(view: ShowView) -> ShowResponse:
    show = view.show
    cover_url = (
        f"/api/shows/{show.id}/cover?v={int(show.updated_at.timestamp())}"
        if show.cover_key
        else None
    )
    return ShowResponse(
        id=show.id,
        title=show.title,
        slug=show.slug,
        slug_locked=view.slug_locked,
        topic=show.topic,
        description=show.description,
        language=show.language,
        target_minutes=show.target_minutes,
        style=show.style,
        prompt_override=show.prompt_override,
        ranking_hints=show.ranking_hints,
        llm_provider=show.llm_provider,
        llm_model=show.llm_model,
        items_per_episode=show.items_per_episode,
        schedule_kind=show.schedule_kind,
        schedule_time=show.schedule_time,
        schedule_weekday=show.schedule_weekday,
        schedule_monthday=show.schedule_monthday,
        timezone=show.timezone,
        paused=show.paused,
        auto_publish=show.auto_publish,
        next_run_at=show.next_run_at,
        feed_author=show.feed_author,
        feed_email=show.feed_email,
        feed_category=show.feed_category,
        feed_explicit=show.feed_explicit,
        cover_url=cover_url,
        episode_count=view.episode_count,
        last_run_status=view.last_run_status,
        last_episode_at=view.last_episode_at,
        created_at=show.created_at,
        updated_at=show.updated_at,
        warnings=view.warnings,
    )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, service.ShowNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Show not found")
    if isinstance(exc, service.ShowConflict):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


SERVICE_ERRORS = (service.ShowNotFound, service.ShowConflict, service.ShowInvalid)


@router.get("", response_model=list[ShowResponse])
async def list_shows(user: CurrentUser, session: SessionDep) -> list[ShowResponse]:
    return [response_for(view) for view in await service.list_shows(session, user.id)]


@router.post("", response_model=ShowResponse, status_code=status.HTTP_201_CREATED)
async def create_show(
    body: ShowCreate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    resolver: ResolverDep,
    redis: RedisDep,
) -> ShowResponse:
    try:
        view = await service.create_show(session, resolver, redis, settings, user.id, body)
    except SERVICE_ERRORS as exc:
        raise _http_error(exc) from exc
    return response_for(view)


@router.get("/{show_id}", response_model=ShowResponse)
async def get_show(show_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> ShowResponse:
    try:
        return response_for(await service.get_show(session, user.id, show_id))
    except SERVICE_ERRORS as exc:
        raise _http_error(exc) from exc


@router.patch("/{show_id}", response_model=ShowResponse)
async def update_show(
    show_id: uuid.UUID,
    body: ShowUpdate,
    user: CurrentUser,
    session: SessionDep,
    resolver: ResolverDep,
    redis: RedisDep,
) -> ShowResponse:
    try:
        view = await service.update_show(session, resolver, redis, user.id, show_id, body)
    except SERVICE_ERRORS as exc:
        raise _http_error(exc) from exc
    return response_for(view)


@router.delete("/{show_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_show(
    show_id: uuid.UUID, user: CurrentUser, session: SessionDep, storage: StorageDep
) -> None:
    try:
        await service.delete_show(session, storage, user.id, show_id)
    except SERVICE_ERRORS as exc:
        raise _http_error(exc) from exc
