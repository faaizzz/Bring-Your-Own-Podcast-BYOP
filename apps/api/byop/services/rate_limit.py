from dataclasses import dataclass

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after: int = 0


async def hit(redis: Redis, key: str, limit: int, window_seconds: int) -> RateLimitResult:
    """Count one attempt in a fixed window; deny once `limit` attempts were made.

    Fails open when Redis is unreachable: the health check reports that outage, and
    locking the admin out of their own instance would be worse.
    """
    try:
        pipe = redis.pipeline(transaction=True)
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        pipe.ttl(key)
        count, _, ttl = await pipe.execute()
    except RedisError:
        log.warning("rate_limit_unavailable", key_prefix=key.split(":", 2)[:2])
        return RateLimitResult(allowed=True)
    if int(count) > limit:
        return RateLimitResult(allowed=False, retry_after=max(int(ttl), 1))
    return RateLimitResult(allowed=True)
