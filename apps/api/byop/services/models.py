import json
from decimal import Decimal

import structlog
from redis.asyncio import Redis

from byop.providers.llm import LLMProvider, ModelInfo
from byop.services import cache
from byop.services.credentials import ProviderConfig

CACHE_TTL_SECONDS = 3600

log = structlog.get_logger(__name__)


def cache_key(config: ProviderConfig) -> str:
    return cache.cache_key("models", config)


def _encode(models: list[ModelInfo]) -> str:
    return json.dumps(
        [
            {
                "id": m.id,
                "name": m.name,
                "context_length": m.context_length,
                "prompt": str(m.prompt_price_per_million) if m.prompt_price_per_million else None,
                "completion": (
                    str(m.completion_price_per_million) if m.completion_price_per_million else None
                ),
                "parameters": list(m.supported_parameters),
                "outputs": list(m.output_modalities),
                "web_search": m.web_search,
            }
            for m in models
        ]
    )


def _decode(raw: str) -> list[ModelInfo]:
    return [
        ModelInfo(
            id=item["id"],
            name=item["name"],
            context_length=item["context_length"],
            prompt_price_per_million=Decimal(item["prompt"]) if item["prompt"] else None,
            completion_price_per_million=Decimal(item["completion"])
            if item["completion"]
            else None,
            # Absent in entries cached before capabilities were captured.
            supported_parameters=tuple(item.get("parameters", ())),
            output_modalities=tuple(item.get("outputs", ())),
            web_search=item.get("web_search"),
        )
        for item in json.loads(raw)
    ]


async def list_models_cached(
    redis: Redis, llm: LLMProvider, config: ProviderConfig
) -> list[ModelInfo]:
    """The provider's model list, cached for an hour. Redis trouble degrades to a live call."""
    key = cache_key(config)
    cached = await cache.read(redis, key)
    if cached is not None:
        try:
            return _decode(cached)
        except (ValueError, KeyError):
            log.warning("models_cache_corrupt")

    models = await llm.list_models()
    await cache.write(redis, key, _encode(models), CACHE_TTL_SECONDS)
    return models
