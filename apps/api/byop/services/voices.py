import json

import structlog
from redis.asyncio import Redis

from byop.providers.tts import TTSProvider, Voice
from byop.services import cache
from byop.services.credentials import ProviderConfig

CACHE_TTL_SECONDS = 3600

log = structlog.get_logger(__name__)


def cache_key(config: ProviderConfig) -> str:
    return cache.cache_key("voices", config)


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


async def list_voices_cached(redis: Redis, tts: TTSProvider, config: ProviderConfig) -> list[Voice]:
    """The provider's voices, cached for an hour. Redis trouble degrades to a live call."""
    key = cache_key(config)
    cached = await cache.read(redis, key)
    if cached is not None:
        try:
            return _decode(cached)
        except (ValueError, TypeError):
            log.warning("voices_cache_corrupt")

    voices = await tts.list_voices()
    if voices:  # never pin an empty answer (e.g. a server still loading) for an hour
        await cache.write(redis, key, _encode(voices), CACHE_TTL_SECONDS)
    return voices
