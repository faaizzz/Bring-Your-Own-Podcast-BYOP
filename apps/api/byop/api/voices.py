from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from redis.asyncio import Redis

from byop.api.deps import CurrentUser, StorageDep
from byop.api.integrations import ResolverDep
from byop.models.enums import CredentialProvider
from byop.providers.tts import (
    TTSError,
    TTSParamError,
    UnsupportedTTSProvider,
    get_tts,
    voice_param_problems,
)
from byop.redis_client import get_redis
from byop.schemas.speaker import TTSProviderName
from byop.schemas.voices import DefaultProviderResponse, VoicePreviewRequest, VoiceResponse
from byop.services.credentials import CredentialDecryptionError, ProviderNotConfigured
from byop.services.defaults import default_tts_provider
from byop.services.validation import error_detail, param_errors
from byop.services.voice_preview import render_preview
from byop.services.voices import list_voices_cached

router = APIRouter(prefix="/voices", tags=["voices"])


@router.get("/default-provider", response_model=DefaultProviderResponse)
async def get_default_provider(user: CurrentUser, resolver: ResolverDep) -> DefaultProviderResponse:
    """The TTS provider to preselect: a configured paid one, else Kokoro when it is running."""
    default = await default_tts_provider(resolver, user.id)
    return DefaultProviderResponse(provider=default.value if default else None)


@router.get("", response_model=list[VoiceResponse])
async def list_voices(
    user: CurrentUser,
    resolver: ResolverDep,
    redis: Annotated[Redis, Depends(get_redis)],
    provider: Annotated[TTSProviderName | None, Query()] = None,
) -> list[VoiceResponse]:
    """Voices offered by a text-to-speech provider (cached for an hour).

    Without `provider` the default one is used (see `/voices/default-provider`).
    """
    if provider is None:
        default = await default_tts_provider(resolver, user.id)
        if default is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "No text-to-speech provider is configured"
            )
        name = default
    else:
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


@router.post("/preview", response_class=Response, responses={200: {"content": {"audio/mpeg": {}}}})
async def preview_voice(
    body: VoicePreviewRequest, user: CurrentUser, resolver: ResolverDep, storage: StorageDep
) -> Response:
    """A short MP3 of a voice with the given parameters. Identical requests are cached."""
    name = CredentialProvider(body.provider)
    if problems := voice_param_problems(name, body.params):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=error_detail(param_errors(("body", "params"), problems)),
        )
    try:
        config = await resolver.get(user.id, name)
        tts = get_tts(name, config)
    except (ProviderNotConfigured, CredentialDecryptionError, UnsupportedTTSProvider) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    try:
        try:
            clip = await render_preview(
                storage, tts, voice_id=body.voice_id, params=body.params, text=body.text
            )
        finally:
            await tts.aclose()
    except TTSParamError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except TTSError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Could not create the preview: {exc}"
        ) from exc
    return Response(
        clip, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=3600"}
    )
