from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.asyncio import Redis

from byop.api.deps import CurrentUser
from byop.api.integrations import ResolverDep
from byop.models.enums import CredentialProvider
from byop.providers.tts import TTSError, UnsupportedTTSProvider, get_tts
from byop.redis_client import get_redis
from byop.schemas.voices import VoiceResponse
from byop.services.credentials import CredentialDecryptionError, ProviderNotConfigured
from byop.services.voices import list_voices_cached

router = APIRouter(prefix="/voices", tags=["voices"])

TTSProviderName = Literal["openai", "elevenlabs", "openrouter"]


@router.get("", response_model=list[VoiceResponse])
async def list_voices(
    user: CurrentUser,
    resolver: ResolverDep,
    redis: Annotated[Redis, Depends(get_redis)],
    provider: Annotated[TTSProviderName, Query()] = "openai",
) -> list[VoiceResponse]:
    """Voices offered by a text-to-speech provider (cached for an hour)."""
    name = CredentialProvider(provider)
    try:
        config = await resolver.get(user.id, name)
        tts = get_tts(name, config)
    except (ProviderNotConfigured, CredentialDecryptionError, UnsupportedTTSProvider) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    try:
        try:
            voices = await list_voices_cached(redis, tts, config)
        finally:
            await tts.aclose()
    except TTSError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Could not list voices: {exc}") from exc
    return [
        VoiceResponse(
            id=v.id,
            name=v.name,
            language=v.language,
            gender=v.gender,
            preview_url=v.preview_url,
        )
        for v in voices
    ]
