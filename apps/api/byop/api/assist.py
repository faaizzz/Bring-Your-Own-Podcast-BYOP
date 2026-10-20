from fastapi import APIRouter, HTTPException, status

from byop.api.deps import CurrentUser, SessionDep, SettingsDep
from byop.api.integrations import ResolverDep
from byop.schemas.assist import AssistRequest, PersonaDraft, StyleDraft
from byop.services import assist as service

router = APIRouter(prefix="/assist", tags=["assist"])


@router.post("/style", response_model=StyleDraft)
async def design_style(
    body: AssistRequest,
    user: CurrentUser,
    session: SessionDep,
    resolver: ResolverDep,
    settings: SettingsDep,
) -> StyleDraft:
    """A style drafted from a brief. Nothing is saved: the draft is for the person to edit.

    `422` when no model is chosen or set up (the message says what to do); `502` with the
    provider's own reason when the model fails.
    """
    try:
        return await service.design_style(session, resolver, settings, user.id, body)
    except service.AssistUnavailable as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except service.AssistFailed as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.post("/persona", response_model=PersonaDraft)
async def design_persona(
    body: AssistRequest,
    user: CurrentUser,
    session: SessionDep,
    resolver: ResolverDep,
    settings: SettingsDep,
) -> PersonaDraft:
    """A speaker persona drafted from a brief. Nothing is saved."""
    try:
        return await service.design_persona(session, resolver, settings, user.id, body)
    except service.AssistUnavailable as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except service.AssistFailed as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
