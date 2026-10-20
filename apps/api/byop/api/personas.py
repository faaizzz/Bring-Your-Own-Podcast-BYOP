import uuid

from fastapi import APIRouter, HTTPException, Response, status

from byop.api.deps import CurrentUser, SessionDep
from byop.models import Persona
from byop.schemas.personas import PersonaIn, PersonaResponse, PersonaUpdate
from byop.services import personas as service
from byop.services.validation import FieldValidationError, error_detail

router = APIRouter(prefix="/personas", tags=["personas"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Persona not found")


def _out(persona: Persona) -> PersonaResponse:
    return PersonaResponse(
        id=persona.id,
        name=persona.name,
        persona=persona.persona,
        tts_provider=persona.tts_provider,
        voice_id=persona.voice_id,
        voice_params=persona.voice_params,  # type: ignore[arg-type]  # validated on the way in
        created_at=persona.created_at,
        updated_at=persona.updated_at,
    )


@router.get("", response_model=list[PersonaResponse])
async def list_personas(user: CurrentUser, session: SessionDep) -> list[PersonaResponse]:
    return [_out(p) for p in await service.list_personas(session, user.id)]


@router.post("", response_model=PersonaResponse, status_code=status.HTTP_201_CREATED)
async def create_persona(
    body: PersonaIn, user: CurrentUser, session: SessionDep
) -> PersonaResponse:
    try:
        return _out(await service.create_persona(session, user.id, body))
    except FieldValidationError as exc:
        raise _invalid(exc) from exc
    except service.PersonaConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.patch("/{persona_id}", response_model=PersonaResponse)
async def update_persona(
    persona_id: uuid.UUID, body: PersonaUpdate, user: CurrentUser, session: SessionDep
) -> PersonaResponse:
    try:
        return _out(await service.update_persona(session, user.id, persona_id, body))
    except service.PersonaNotFound as exc:
        raise NOT_FOUND from exc
    except FieldValidationError as exc:
        raise _invalid(exc) from exc
    except service.PersonaConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.delete("/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_persona(persona_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Response:
    try:
        await service.delete_persona(session, user.id, persona_id)
    except service.PersonaNotFound as exc:
        raise NOT_FOUND from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _invalid(exc: FieldValidationError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, error_detail(exc.errors))
