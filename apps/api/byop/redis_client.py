from collections.abc import AsyncIterator
from functools import lru_cache

from redis.asyncio import Redis

from byop.config import get_settings


@lru_cache
def get_redis_client() -> Redis:
    client: Redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return client


async def get_redis() -> AsyncIterator[Redis]:
    """FastAPI dependency: the shared async Redis client."""
    yield get_redis_client()


async def close_redis() -> None:
    if get_redis_client.cache_info().currsize:
        await get_redis_client().aclose()
