from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from byop.api.deps import CurrentUser, SessionDep, SettingsDep
from byop.models.enums import CredentialProvider
from byop.schemas.integrations import (
    IntegrationResponse,
    IntegrationTestResponse,
    IntegrationUpdate,
)
from byop.services.credentials import (
    REQUIRES_API_KEY,
    REQUIRES_BASE_URL,
    CredentialDecryptionError,
    CredentialResolver,
    CredentialView,
    ProviderNotConfigured,
)
from byop.services.integration_check import check_provider
from byop.services.user_settings import request_interval, save_request_interval

router = APIRouter(prefix="/integrations", tags=["integrations"])


def get_resolver(session: SessionDep, settings: SettingsDep) -> CredentialResolver:
    return CredentialResolver(session, settings)


ResolverDep = Annotated[CredentialResolver, Depends(get_resolver)]


def _response(view: CredentialView, min_interval_s: float = 0) -> IntegrationResponse:
    return IntegrationResponse(
        provider=view.provider,
        source=view.source,
        enabled=view.enabled,
        api_key_masked=view.api_key_masked,
        base_url=view.base_url,
        extra_masked=dict(view.extra_masked),
        problem=view.problem,
        min_interval_s=min_interval_s,
    )


def _built_in(provider: CredentialProvider) -> None:
    """OpenAI-compatible servers are connections (`/api/connections`), not integrations."""
    if provider is CredentialProvider.OPENAI_COMPATIBLE:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "OpenAI-compatible servers are managed under /api/connections",
        )


@router.get("/{provider}", response_model=IntegrationResponse)
async def get_integration(
    provider: CredentialProvider, user: CurrentUser, resolver: ResolverDep, session: SessionDep
) -> IntegrationResponse:
    _built_in(provider)
    return _response(
        await resolver.view(user.id, provider),
        await request_interval(session, user.id, provider.value),
    )


@router.put("/{provider}", response_model=IntegrationResponse)
async def put_integration(
    provider: CredentialProvider,
    body: IntegrationUpdate,
    user: CurrentUser,
    resolver: ResolverDep,
    session: SessionDep,
) -> IntegrationResponse:
    _built_in(provider)
    if body.model_fields_set == {"min_interval_s"} and body.min_interval_s is not None:
        # Only the wait changed: no override is made or touched, so a key from `.env` keeps working.
        await save_request_interval(session, user.id, provider.value, body.min_interval_s)
        return _response(
            await resolver.view(user.id, provider),
            await request_interval(session, user.id, provider.value),
        )
    api_key = body.api_key.get_secret_value() if body.api_key else None
    base_url = str(body.base_url).rstrip("/") if body.base_url else None

    # A first-time override must be usable; later updates may omit what is already stored.
    stored = await resolver.stored_override(user.id, provider)
    has_key = api_key or (stored is not None and stored.api_key is not None)
    has_url = base_url or (stored is not None and stored.base_url)
    if provider in REQUIRES_API_KEY and not has_key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "An API key is required")
    if provider in REQUIRES_BASE_URL and not has_url:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A base URL is required")

    await resolver.save(
        user.id,
        provider,
        api_key=api_key,
        base_url=base_url,
        extra=body.extra,
        enabled=body.enabled,
    )
    if body.min_interval_s is not None:
        await save_request_interval(session, user.id, provider.value, body.min_interval_s)
    return _response(
        await resolver.view(user.id, provider),
        await request_interval(session, user.id, provider.value),
    )


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_integration(
    provider: CredentialProvider, user: CurrentUser, resolver: ResolverDep
) -> None:
    """Remove the user's override; the environment value (if any) applies again."""
    _built_in(provider)
    await resolver.delete(user.id, provider)


@router.post("/{provider}/test", response_model=IntegrationTestResponse)
async def test_integration(
    provider: CredentialProvider, user: CurrentUser, resolver: ResolverDep
) -> IntegrationTestResponse:
    _built_in(provider)
    try:
        config = await resolver.get(user.id, provider)
    except ProviderNotConfigured:
        return IntegrationTestResponse(ok=False, detail="Not configured")
    except CredentialDecryptionError as exc:
        return IntegrationTestResponse(ok=False, detail=str(exc))
    result = await check_provider(config)
    return IntegrationTestResponse(ok=result.ok, detail=result.detail)
