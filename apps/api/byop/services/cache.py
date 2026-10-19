import hashlib

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from byop.services.credentials import ProviderConfig

log = structlog.get_logger(__name__)


def cache_key(prefix: str, config: ProviderConfig) -> str:
    """`prefix:provider:fingerprint`; a changed key or base URL must not see another's data."""
    base = config.base_url or ""
    key = config.api_key.get_secret_value() if config.api_key else ""
    # Custom headers can change what a server answers (a gateway routes on them).
    headers = "\n".join(f"{n}={v}" for n, v in sorted(config.headers.items()))
    fingerprint = hashlib.sha256(f"{base}\n{key}\n{headers}".encode()).hexdigest()[:16]
    kind = f"conn-{config.connection_id}" if config.connection_id else config.provider.value
    return f"{prefix}:{kind}:{fingerprint}"


async def read(redis: Redis, key: str) -> str | None:
    """Cached text, or None on a miss or when Redis is unavailable."""
    try:
        value = await redis.get(key)
    except RedisError:
        log.warning("cache_read_failed", key_prefix=key.split(":", 1)[0])
        return None
    return str(value) if value else None


async def write(redis: Redis, key: str, value: str, ttl_seconds: int) -> None:
    try:
        await redis.set(key, value, ex=ttl_seconds)
    except RedisError:
        log.warning("cache_write_failed", key_prefix=key.split(":", 1)[0])
