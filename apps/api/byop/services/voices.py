import json

import structlog
from redis.asyncio import Redis

from byop.providers.tts import SpeechModel, TTSProvider, Voice
from byop.services import cache
from byop.services.credentials import ProviderConfig

CACHE_TTL_SECONDS = 3600

log = structlog.get_logger(__name__)


def cache_key(config: ProviderConfig, model: str | None = None) -> str:
    key = cache.cache_key("voices", config)
    return f"{key}:{model}" if model else key


def models_cache_key(config: ProviderConfig) -> str:
    return cache.cache_key("speech_models", config)


def _encode(voices: list[Voice]) -> str:
    return json.dumps(
        [
            {
                "id": v.id,
                "name": v.name,
                "language": v.language,
                "gender": v.gender,
                "preview_url": v.preview_url,
            }
            for v in voices
        ]
    )


def _decode(raw: str) -> list[Voice]:
    return [Voice(**item) for item in json.loads(raw)]


async def list_voices_cached(
    redis: Redis, tts: TTSProvider, config: ProviderConfig, model: str | None = None
) -> list[Voice]:
    """The provider's voices, cached for an hour. Redis trouble degrades to a live call.

    `model` only matters to providers whose voices follow the model (`voices_follow_model`).
    """
    model = model if tts.quirks.voices_follow_model else None
    key = cache_key(config, model)
    cached = await cache.read(redis, key)
    if cached is not None:
        try:
            return _decode(cached)
        except (ValueError, TypeError):
            log.warning("voices_cache_corrupt")

    voices = await tts.list_voices(model)
    if voices:  # never pin an empty answer (e.g. a server still loading) for an hour
        await cache.write(redis, key, _encode(voices), CACHE_TTL_SECONDS)
    return voices


def _encode_models(models: list[SpeechModel]) -> str:
    return json.dumps(
        [
            {"id": m.id, "name": m.name, "description": m.description, "voices": list(m.voices)}
            for m in models
        ]
    )


def _decode_models(raw: str) -> list[SpeechModel]:
    return [
        SpeechModel(
            id=item["id"],
            name=item["name"],
            description=item.get("description"),
            voices=tuple(item.get("voices", ())),
        )
        for item in json.loads(raw)
    ]


async def list_speech_models_cached(
    redis: Redis, tts: TTSProvider, config: ProviderConfig
) -> list[SpeechModel]:
    """The provider's speech models, cached for an hour (an empty answer is not kept)."""
    key = models_cache_key(config)
    cached = await cache.read(redis, key)
    if cached is not None:
        try:
            return _decode_models(cached)
        except (ValueError, KeyError, TypeError):
            log.warning("speech_models_cache_corrupt")

    models = await tts.list_models()
    if models:
        await cache.write(redis, key, _encode_models(models), CACHE_TTL_SECONDS)
    return models
