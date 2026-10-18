import uuid

from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from byop.api.deps import CurrentUser, SessionDep, StorageDep
from byop.api.shows import response_for
from byop.schemas.show import ShowResponse
from byop.services import covers as service
from byop.services.shows import ShowNotFound
from byop.storage import StorageError

# Upload and removal need a session; reading is public so feeds and directories can fetch it.
router = APIRouter(prefix="/shows/{show_id}/cover", tags=["covers"])
public_router = APIRouter(prefix="/shows/{show_id}/cover", tags=["covers"])

StorageDown = HTTPException(status.HTTP_502_BAD_GATEWAY, "Media storage is unavailable")


@router.post("", response_model=ShowResponse)
async def upload_cover(
    show_id: uuid.UUID,
    file: UploadFile,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
) -> ShowResponse:
    """Replace the show's cover with a PNG or JPEG; it is cropped square and resized."""
    data = await file.read(service.MAX_UPLOAD_BYTES + 1)
    try:
        view = await service.set_cover(session, storage, user.id, show_id, data)
    except ShowNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Show not found") from exc
    except service.CoverTooLarge as exc:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(exc)) from exc
    except service.CoverInvalid as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except StorageError as exc:
        raise StorageDown from exc
    return response_for(view)


@router.delete("", response_model=ShowResponse)
async def delete_cover(
    show_id: uuid.UUID, user: CurrentUser, session: SessionDep, storage: StorageDep
) -> ShowResponse:
    try:
        return response_for(await service.remove_cover(session, storage, user.id, show_id))
    except ShowNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Show not found") from exc
    except StorageError as exc:
        raise StorageDown from exc


@public_router.get("", response_class=StreamingResponse)
async def get_cover(
    show_id: uuid.UUID, session: SessionDep, storage: StorageDep
) -> StreamingResponse:
    try:
        info, stream = await service.open_cover(session, storage, show_id)
    except ShowNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No cover") from exc
    except StorageError as exc:
        raise StorageDown from exc
    return StreamingResponse(
        stream,
        media_type=info.content_type or "image/jpeg",
        headers={
            "Content-Length": str(info.size),
            # The URL carries a version (?v=), so a long cache is safe.
            "Cache-Control": "public, max-age=86400",
        },
    )
