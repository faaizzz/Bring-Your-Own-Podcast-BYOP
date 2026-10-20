from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from redis.asyncio import Redis

from byop.api.deps import CurrentUser, SessionDep, StorageDep
from byop.api.integrations import ResolverDep
from byop.models.enums import CredentialProvider
from byop.providers.tts import (
    TTSError,
    TTSParamError,
    UnsupportedTTSProvider,
    get_tts,
    quirks_for,
    voice_param_problems,
)
from byop.redis_client import get_redis
from byop.schemas.speaker import SpeakerIn, TTSProviderName
from byop.schemas.voices import (
    DefaultProviderResponse,
    SpeechModelResponse,
    SpeechModelsResponse,
    VoicePreviewRequest,
    VoiceResponse,
)
from byop.services.credentials import CredentialDecryptionError, ProviderNotConfigured
from byop.services.defaults import default_tts_provider
from byop.services.provider_ref import ProviderRef
from byop.services.speaker_defaults import default_speakers
from byop.services.usage import capture_usage
from byop.services.validation import error_detail, param_errors
from byop.services.voice_preview import render_preview
from byop.services.voices import list_speech_models_cached, list_voices_cached

router = APIRouter(prefix="/voices", tags=["voices"])


@router.get("/default-provider", response_model=DefaultProviderResponse)
async def get_default_provider(user: CurrentUser, resolver: ResolverDep) -> DefaultProviderResponse:
    """The TTS provider to preselect: a configured paid one, else Kokoro when it is running."""
    default = await default_tts_provider(resolver, user.id)
    return DefaultProviderResponse(provider=default.value if default else None)


@router.get("/default-speakers", response_model=list[SpeakerIn])
async def get_default_speakers(user: CurrentUser, resolver: ResolverDep) -> list[SpeakerIn]:
    """The two hosts a new show starts with (what the create-show wizard pre-fills)."""
    provider = await default_tts_provider(resolver, user.id) or CredentialProvider.KOKORO
    return default_speakers(provider)


@router.get("/models", response_model=SpeechModelsResponse)
async def list_speech_models(
    user: CurrentUser,
    resolver: ResolverDep,
    redis: Annotated[Redis, Depends(get_redis)],
    provider: Annotated[TTSProviderName, Query()],
) -> SpeechModelsResponse:
    """The speech models of a provider (cached for an hour) and which voice parameter names one.

    `models` is empty for a provider without a list (a connection whose server has no `/models`);
    `param` is null for one without a choice of model (Kokoro).
    """
    ref = ProviderRef.parse(provider)
    quirks = quirks_for(ref.kind)
    try:
        config = await resolver.get_ref(user.id, ref, "tts")
        tts = get_tts(config.provider, config)
    except (ProviderNotConfigured, CredentialDecryptionError, UnsupportedTTSProvider) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    try:
        try:
            models = (
                await list_speech_models_cached(redis, tts, config) if quirks.model_param else []
            )
        finally:
            await tts.aclose()
    except TTSError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Could not list speech models: {exc}"
        ) from exc
    return SpeechModelsResponse(
        param=quirks.model_param,
        required=quirks.model_param is not None and quirks.model_param in quirks.required_params,
        default=tts.default_model if quirks.model_param else None,
        voices_follow_model=quirks.voices_follow_model,
        models=[
            SpeechModelResponse(id=m.id, name=m.name, description=m.description) for m in models
        ],
    )


@router.get("", response_model=list[VoiceResponse])
async def list_voices(
    user: CurrentUser,
    resolver: ResolverDep,
    redis: Annotated[Redis, Depends(get_redis)],
    provider: Annotated[TTSProviderName | None, Query()] = None,
    model: Annotated[str | None, Query(max_length=200)] = None,
) -> list[VoiceResponse]:
    """Voices offered by a text-to-speech provider (cached for an hour).

    Without `provider` the default one is used (see `/voices/default-provider`). `model` is the
    speech model, for providers whose voices depend on it (OpenRouter).
    """
    if provider is None:
        default = await default_tts_provider(resolver, user.id)
        if default is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "No text-to-speech provider is configured"
            )
        ref = ProviderRef.of(default)
    else:
        ref = ProviderRef.parse(provider)
    try:
        config = await resolver.get_ref(user.id, ref, "tts")
        tts = get_tts(config.provider, config)
    except (ProviderNotConfigured, CredentialDecryptionError, UnsupportedTTSProvider) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    try:
        try:
            voices = await list_voices_cached(redis, tts, config, model)
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
    body: VoicePreviewRequest,
    user: CurrentUser,
    session: SessionDep,
    resolver: ResolverDep,
    storage: StorageDep,
) -> Response:
    """A short MP3 of a voice with the given parameters. Identical requests are cached."""
    ref = ProviderRef.parse(body.provider)
    if problems := voice_param_problems(ref.kind, body.params):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=error_detail(param_errors(("body", "params"), problems)),
        )
    try:
        config = await resolver.get_ref(user.id, ref, "tts")
        tts = get_tts(config.provider, config)
    except (ProviderNotConfigured, CredentialDecryptionError, UnsupportedTTSProvider) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    try:
        try:
            async with capture_usage(session, user.id):
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
