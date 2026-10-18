import uuid

from fastapi import APIRouter, HTTPException, status

from byop.api.deps import CurrentUser, SessionDep, SettingsDep
from byop.models import Source
from byop.schemas.source import (
    SourceCreate,
    SourceResponse,
    SourceUpdate,
    SourceValidateRequest,
    SourceValidation,
)
from byop.services import sources as service
from byop.services.shows import ShowNotFound, get_show
from byop.services.validation import FieldValidationError, error_detail

router = APIRouter(prefix="/shows/{show_id}/sources", tags=["sources"])


def _response(source: Source) -> SourceResponse:
    return SourceResponse(
        id=source.id,
        show_id=source.show_id,
        kind=source.kind,
        value=source.value,
        name=source.name,
        origin=source.origin,
        enabled=source.enabled,
        last_fetched_at=source.last_fetched_at,
        last_error=source.last_error,
        created_at=source.created_at,
    )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ShowNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Show not found")
    if isinstance(exc, service.SourceNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    if isinstance(exc, service.SourceConflict):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    assert isinstance(exc, FieldValidationError)
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=error_detail(exc.errors))


ERRORS = (ShowNotFound, service.SourceNotFound, service.SourceConflict, FieldValidationError)


@router.get("", response_model=list[SourceResponse])
async def list_sources(
    show_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[SourceResponse]:
    try:
        return [_response(s) for s in await service.list_sources(session, user.id, show_id)]
    except ERRORS as exc:
        raise _http_error(exc) from exc


@router.post("", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(
    show_id: uuid.UUID,
    body: SourceCreate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> SourceResponse:
    """Add a source. An RSS feed is fetched first and rejected, with the reason, if unusable."""
    try:
        source = await service.create_source(
            session,
            user.id,
            show_id,
            body,
            allow_private=settings.sources_allow_private_networks,
        )
    except ERRORS as exc:
        raise _http_error(exc) from exc
    return _response(source)


@router.post("/validate", response_model=SourceValidation)
async def validate_source(
    show_id: uuid.UUID,
    body: SourceValidateRequest,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> SourceValidation:
    """Fetch an RSS feed without saving it: its title and latest entries, or why it is unusable."""
    try:
        await get_show(session, user.id, show_id)
        return await service.validate_source(
            body.kind,
            body.value,
            allow_private=settings.sources_allow_private_networks,
        )
    except ERRORS as exc:
        raise _http_error(exc) from exc


@router.patch("/{source_id}", response_model=SourceResponse)
async def update_source(
    show_id: uuid.UUID,
    source_id: uuid.UUID,
    body: SourceUpdate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> SourceResponse:
    try:
        source = await service.update_source(
            session,
            user.id,
            show_id,
            source_id,
            body,
            allow_private=settings.sources_allow_private_networks,
        )
    except ERRORS as exc:
        raise _http_error(exc) from exc
    return _response(source)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    show_id: uuid.UUID, source_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> None:
    try:
        await service.delete_source(session, user.id, show_id, source_id)
    except ERRORS as exc:
        raise _http_error(exc) from exc
