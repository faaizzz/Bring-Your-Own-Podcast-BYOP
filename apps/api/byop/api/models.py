from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.asyncio import Redis

from byop.api.deps import CurrentUser
from byop.api.integrations import ResolverDep
from byop.models.enums import CredentialProvider
from byop.providers.llm import LLMError, UnsupportedLLMProvider, get_llm
from byop.redis_client import get_redis
from byop.schemas.models import ModelResponse
from byop.services.credentials import CredentialDecryptionError, ProviderNotConfigured
from byop.services.models import list_models_cached

router = APIRouter(prefix="/models", tags=["models"])

LLMProviderName = Literal["openrouter", "openai", "openai_compatible"]


@router.get("", response_model=list[ModelResponse])
async def list_models(
    user: CurrentUser,
    resolver: ResolverDep,
    redis: Annotated[Redis, Depends(get_redis)],
    provider: Annotated[LLMProviderName, Query()] = "openrouter",
) -> list[ModelResponse]:
    """Models offered by an LLM provider (cached for an hour)."""
    name = CredentialProvider(provider)
    try:
        config = await resolver.get(user.id, name)
        llm = get_llm(name, config)
    except ProviderNotConfigured as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except (CredentialDecryptionError, UnsupportedLLMProvider) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    try:
        try:
            models = await list_models_cached(redis, llm, config)
        finally:
            await llm.aclose()
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Could not list models: {exc}") from exc
    except Exception as exc:  # the SDK can raise its own errors when listing
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Could not list models from {provider}"
        ) from exc
    return [
        ModelResponse(
            id=m.id,
            name=m.name,
            context_length=m.context_length,
            prompt_price_per_million=m.prompt_price_per_million,
            completion_price_per_million=m.completion_price_per_million,
        )
        for m in models
    ]
