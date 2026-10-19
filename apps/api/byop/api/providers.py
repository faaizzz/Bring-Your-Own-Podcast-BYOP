from typing import Annotated, Literal

from fastapi import APIRouter, Query

from byop.api.deps import CurrentUser, SessionDep
from byop.api.integrations import ResolverDep
from byop.schemas.providers import ProviderOption
from byop.services.provider_options import provider_options

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("", response_model=list[ProviderOption])
async def list_providers(
    user: CurrentUser,
    session: SessionDep,
    resolver: ResolverDep,
    capability: Annotated[Literal["llm", "tts"], Query()],
) -> list[ProviderOption]:
    """The providers a show (llm) or a speaker (tts) can use: built-in ones and connections."""
    return await provider_options(session, resolver, user.id, capability)
