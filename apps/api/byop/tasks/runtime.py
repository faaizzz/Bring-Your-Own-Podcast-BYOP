from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from byop.config import Settings, get_settings


@asynccontextmanager
async def task_deps() -> AsyncIterator[tuple[AsyncSession, Redis, Settings]]:
    """A database session and Redis client for one Celery task.

    Each task runs in its own event loop (`asyncio.run`), and pooled connections from another
    loop cannot be reused, so these are created fresh and closed afterwards.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session, redis, settings
    finally:
        await redis.aclose()
        await engine.dispose()
