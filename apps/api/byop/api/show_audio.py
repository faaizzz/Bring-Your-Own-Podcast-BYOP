import uuid
from pathlib import Path

import anyio
from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from byop.api.deps import CurrentUser, SessionDep, SettingsDep, StorageDep
from byop.api.shows import response_for
from byop.schemas.show import ShowResponse
from byop.services import show_audio as service
from byop.services.show_audio import AudioKind
from byop.services.shows import ShowNotFound
from byop.storage import StorageError

router = APIRouter(prefix="/shows/{show_id}/audio", tags=["audio"])

StorageDown = HTTPException(status.HTTP_502_BAD_GATEWAY, "Media storage is unavailable")
CHUNK = 1024 * 1024


@router.post("/{kind}", response_model=ShowResponse)
async def upload_audio(
    show_id: uuid.UUID,
    kind: AudioKind,
    file: UploadFile,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> ShowResponse:
    """Set the show's intro, outro or music bed. The upload goes to disk, never into memory."""
    async with anyio.TemporaryDirectory() as tmp:
        target = Path(tmp) / "upload"
        size = 0
        async with await anyio.open_file(target, "wb") as out:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > service.MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status.HTTP_413_CONTENT_TOO_LARGE,
                        f"The file is larger than {service.MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
                    )
                await out.write(chunk)
        try:
            view = await service.set_asset(
                session, storage, user.id, show_id, kind, target, file.filename or ""
            )
        except ShowNotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Show not found") from exc
        except service.AudioInvalid as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        except StorageError as exc:
            raise StorageDown from exc
    return response_for(view, settings)


@router.delete("/{kind}", response_model=ShowResponse)
async def delete_audio(
    show_id: uuid.UUID,
    kind: AudioKind,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> ShowResponse:
    try:
        return response_for(
            await service.remove_asset(session, storage, user.id, show_id, kind), settings
        )
    except ShowNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Show not found") from exc
    except StorageError as exc:
        raise StorageDown from exc


@router.get("/{kind}", response_class=StreamingResponse)
async def get_audio(
    show_id: uuid.UUID, kind: AudioKind, user: CurrentUser, session: SessionDep, storage: StorageDep
) -> StreamingResponse:
    """The clip itself, for previewing it in the app."""
    try:
        info, stream = await service.open_asset(session, storage, user.id, show_id, kind)
    except ShowNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No {kind} clip") from exc
    except StorageError as exc:
        raise StorageDown from exc
    return StreamingResponse(
        stream,
        media_type=info.content_type or "audio/mpeg",
        headers={"Content-Length": str(info.size), "Cache-Control": "private, max-age=3600"},
    )
