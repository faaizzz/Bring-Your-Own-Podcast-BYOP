import uuid

from fastapi import APIRouter, HTTPException, status

from byop.api.deps import CurrentUser, SessionDep
from byop.models import Speaker
from byop.schemas.speaker import SpeakerList, SpeakerResponse
from byop.services import speakers as service
from byop.services.shows import ShowNotFound
from byop.services.validation import FieldValidationError, error_detail

router = APIRouter(prefix="/shows/{show_id}/speakers", tags=["speakers"])


def _response(speaker: Speaker) -> SpeakerResponse:
    return SpeakerResponse(
        id=speaker.id,
        position=speaker.position,
        name=speaker.name,
        persona=speaker.persona,
        tts_provider=speaker.tts_provider,
        voice_id=speaker.voice_id,
        voice_params=speaker.voice_params,  # type: ignore[arg-type]  # validated scalars
        fallback_tts_provider=speaker.fallback_tts_provider,
        fallback_voice_id=speaker.fallback_voice_id,
    )


@router.get("", response_model=list[SpeakerResponse])
async def list_speakers(
    show_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[SpeakerResponse]:
    try:
        return [_response(s) for s in await service.list_speakers(session, user.id, show_id)]
    except ShowNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Show not found") from exc


@router.put("", response_model=list[SpeakerResponse])
async def replace_speakers(
    show_id: uuid.UUID, body: SpeakerList, user: CurrentUser, session: SessionDep
) -> list[SpeakerResponse]:
    """Replace the whole ordered list (1-4 speakers); the order is the speaking order."""
    try:
        saved = await service.replace_speakers(session, user.id, show_id, body)
    except ShowNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Show not found") from exc
    except FieldValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail=error_detail(exc.errors)
        ) from exc
    return [_response(s) for s in saved]
