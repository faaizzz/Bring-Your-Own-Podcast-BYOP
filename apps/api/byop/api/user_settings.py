import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis

from byop.api.deps import CurrentUser, SessionDep, SettingsDep
from byop.api.integrations import ResolverDep
from byop.redis_client import get_redis
from byop.schemas.user_settings import DiscoveryModelSetting, DiscoveryModelUpdate
from byop.services.credentials import CredentialResolver
from byop.services.discovery import (
    DiscoveryRequest,
    DiscoveryUnavailable,
    describe_plan,
    plan_discovery,
)
from byop.services.provider_ref import ProviderRef
from byop.services.user_settings import (
    check_discovery_provider,
    clear_discovery_choice,
    load_discovery_choice,
    save_discovery_choice,
)
from byop.services.validation import FieldValidationError, error_detail
from byop.services.web_search import WebSearch, check_web_search

router = APIRouter(prefix="/settings", tags=["settings"])


async def _current(
    session: SessionDep,
    resolver: CredentialResolver,
    redis: Redis,
    settings: SettingsDep,
    user_id: uuid.UUID,
    warnings: list[str] | None = None,
) -> DiscoveryModelSetting:
    chosen = await load_discovery_choice(session, user_id)
    request = DiscoveryRequest(
        user_id=user_id,
        show_id=None,
        topic="",
        discovery_llm_provider=chosen.provider,
        discovery_llm_model=chosen.model,
    )
    try:
        effective = describe_plan(await plan_discovery(resolver, redis, settings, request))
    except DiscoveryUnavailable:
        effective = None
    return DiscoveryModelSetting(
        provider=chosen.provider,
        model=chosen.model,
        effective=effective,
        warnings=warnings or [],
    )


@router.get("/discovery-model", response_model=DiscoveryModelSetting)
async def get_discovery_model(
    user: CurrentUser,
    session: SessionDep,
    resolver: ResolverDep,
    redis: Annotated[Redis, Depends(get_redis)],
    settings: SettingsDep,
) -> DiscoveryModelSetting:
    """The model saved in Settings (nulls when unset) and the one discovery would use now."""
    return await _current(session, resolver, redis, settings, user.id)


@router.put("/discovery-model", response_model=DiscoveryModelSetting)
async def put_discovery_model(
    body: DiscoveryModelUpdate,
    user: CurrentUser,
    session: SessionDep,
    resolver: ResolverDep,
    redis: Annotated[Redis, Depends(get_redis)],
    settings: SettingsDep,
) -> DiscoveryModelSetting:
    """Save the discovery model. `422` when it cannot search the web; a model whose capability
    cannot be confirmed is saved and comes back with a warning."""
    try:
        await check_discovery_provider(session, user.id, body.provider)
    except FieldValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, error_detail(exc.errors)
        ) from exc
    check = await check_web_search(
        resolver, redis, user.id, ProviderRef.parse(body.provider), body.model
    )
    if check.support is WebSearch.NO:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, check.message)
    await save_discovery_choice(session, user.id, body.provider, body.model)
    warnings = [check.message] if check.support is WebSearch.UNKNOWN and check.message else []
    return await _current(session, resolver, redis, settings, user.id, warnings)


@router.delete("/discovery-model", response_model=DiscoveryModelSetting)
async def delete_discovery_model(
    user: CurrentUser,
    session: SessionDep,
    resolver: ResolverDep,
    redis: Annotated[Redis, Depends(get_redis)],
    settings: SettingsDep,
) -> DiscoveryModelSetting:
    """Forget the saved choice: discovery falls back to .env, the show's model, the default."""
    await clear_discovery_choice(session, user.id)
    return await _current(session, resolver, redis, settings, user.id)
