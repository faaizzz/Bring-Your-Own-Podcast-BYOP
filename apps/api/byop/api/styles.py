import uuid

from fastapi import APIRouter, HTTPException, Response, status

from byop.api.deps import CurrentUser, SessionDep
from byop.schemas.styles import StyleCreate, StyleResponse, StyleUpdate
from byop.services import styles as service

router = APIRouter(prefix="/styles", tags=["styles"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Style not found")


@router.get("", response_model=list[StyleResponse])
async def list_styles(user: CurrentUser, session: SessionDep) -> list[StyleResponse]:
    """The built-in styles (read-only, with the instructions they give the model), then yours."""
    return await service.list_styles(session, user.id)


@router.post("", response_model=StyleResponse, status_code=status.HTTP_201_CREATED)
async def create_style(body: StyleCreate, user: CurrentUser, session: SessionDep) -> StyleResponse:
    try:
        return await service.create_style(session, user.id, body)
    except service.StyleInvalid as exc:
        raise _invalid(exc) from exc
    except service.StyleConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.patch("/{style_id}", response_model=StyleResponse)
async def update_style(
    style_id: uuid.UUID, body: StyleUpdate, user: CurrentUser, session: SessionDep
) -> StyleResponse:
    try:
        return await service.update_style(session, user.id, style_id, body)
    except service.StyleNotFound as exc:
        raise NOT_FOUND from exc
    except service.StyleInvalid as exc:
        raise _invalid(exc) from exc
    except service.StyleConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.delete("/{style_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_style(style_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Response:
    """`409` while shows use the style; the message names them."""
    try:
        await service.delete_style(session, user.id, style_id)
    except service.StyleNotFound as exc:
        raise NOT_FOUND from exc
    except service.StyleConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _invalid(exc: service.StyleInvalid) -> HTTPException:
    detail = [{"loc": ["body", "instructions"], "msg": str(exc), "type": "value_error"}]
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)
