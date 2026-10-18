import hashlib
import json
from decimal import Decimal

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from byop.providers.llm import LLMProvider, ModelInfo
from byop.services.credentials import ProviderConfig

CACHE_TTL_SECONDS = 3600

log = structlog.get_logger(__name__)


def cache_key(config: ProviderConfig) -> str:
    """Per provider and credential: a changed key or base URL must not see another's list."""
    base = config.base_url or ""
    key = config.api_key.get_secret_value() if config.api_key else ""
    fingerprint = hashlib.sha256(f"{base}\n{key}".encode()).hexdigest()[:16]
    return f"models:{config.provider.value}:{fingerprint}"


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
        )
        for item in json.loads(raw)
    ]


async def list_models_cached(
    redis: Redis, llm: LLMProvider, config: ProviderConfig
) -> list[ModelInfo]:
    """The provider's model list, cached for an hour. Redis trouble degrades to a live call."""
    key = cache_key(config)
    try:
        cached = await redis.get(key)
        if cached:
            return _decode(str(cached))
    except (RedisError, ValueError, KeyError):
        log.warning("models_cache_read_failed")

    models = await llm.list_models()
    try:
        await redis.set(key, _encode(models), ex=CACHE_TTL_SECONDS)
    except RedisError:
        log.warning("models_cache_write_failed")
    return models
