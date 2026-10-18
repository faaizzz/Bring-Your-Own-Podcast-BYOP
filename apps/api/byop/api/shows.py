import uuid

from fastapi import APIRouter, HTTPException, status

from byop.api.deps import CurrentUser, RedisDep, SessionDep, SettingsDep, StorageDep
from byop.api.integrations import ResolverDep
from byop.config import Settings
from byop.schemas.costs import CostEstimate
from byop.schemas.show import ShowCreate, ShowResponse, ShowUpdate
from byop.services import costs as costs_service
from byop.services import shows as service
from byop.services.podcast_feed import feed_url
from byop.services.shows import ShowView

router = APIRouter(prefix="/shows", tags=["shows"])


def response_for(view: ShowView, settings: Settings) -> ShowResponse:
    show = view.show
    version = int(show.updated_at.timestamp())

    def audio_url(kind: str, key: str | None) -> str | None:
        return f"/api/shows/{show.id}/audio/{kind}?v={version}" if key else None

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
        feed_enabled=show.feed_enabled,
        feed_url=feed_url(settings.public_base_url, show.slug),
        cover_url=cover_url,
        intro_url=audio_url("intro", show.intro_key),
        outro_url=audio_url("outro", show.outro_key),
        music_url=audio_url("music", show.music_key),
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
async def list_shows(
    user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> list[ShowResponse]:
    return [response_for(view, settings) for view in await service.list_shows(session, user.id)]


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
    return response_for(view, settings)


@router.post("/{show_id}/pause", response_model=ShowResponse)
async def pause_show(
    show_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> ShowResponse:
    """Stop scheduled runs; manual runs still work."""
    try:
        return response_for(await service.set_paused(session, user.id, show_id, True), settings)
    except service.ShowNotFound as exc:
        raise _http_error(exc) from exc


@router.post("/{show_id}/resume", response_model=ShowResponse)
async def resume_show(
    show_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> ShowResponse:
    """Resume the schedule from the next slot after now."""
    try:
        return response_for(await service.set_paused(session, user.id, show_id, False), settings)
    except service.ShowNotFound as exc:
        raise _http_error(exc) from exc


@router.get("/{show_id}/estimate", response_model=CostEstimate)
async def estimate_cost(
    show_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    resolver: ResolverDep,
    redis: RedisDep,
) -> CostEstimate:
    """What one episode of this show is expected to cost, from its length, model and voices."""
    try:
        show = (await service.get_show(session, user.id, show_id)).show
    except service.ShowNotFound as exc:
        raise _http_error(exc) from exc
    return await costs_service.estimate_episode(
        session,
        settings,
        user.id,
        show,
        extra_llm_price=await costs_service.provider_llm_price(
            resolver, redis, settings, user.id, show
        ),
    )


@router.get("/{show_id}", response_model=ShowResponse)
async def get_show(
    show_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> ShowResponse:
    try:
        return response_for(await service.get_show(session, user.id, show_id), settings)
    except SERVICE_ERRORS as exc:
        raise _http_error(exc) from exc


@router.patch("/{show_id}", response_model=ShowResponse)
async def update_show(
    show_id: uuid.UUID,
    body: ShowUpdate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    resolver: ResolverDep,
    redis: RedisDep,
) -> ShowResponse:
    try:
        view = await service.update_show(session, resolver, redis, user.id, show_id, body)
    except SERVICE_ERRORS as exc:
        raise _http_error(exc) from exc
    return response_for(view, settings)


@router.delete("/{show_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_show(
    show_id: uuid.UUID, user: CurrentUser, session: SessionDep, storage: StorageDep
) -> None:
    try:
        await service.delete_show(session, storage, user.id, show_id)
    except SERVICE_ERRORS as exc:
        raise _http_error(exc) from exc
