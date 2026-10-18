import asyncio
import os
from collections.abc import AsyncIterator

# Settings are validated at import time, so the test environment must exist first.
os.environ["BYOP_SECRET_KEY"] = "test-secret-key-0123456789abcdef"
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine

from byop.db import get_session
from byop.main import create_app
from byop.redis_client import get_redis_client
from byop.security import passwords
from tests.db_utils import TEST_DATABASE_URL, migrate, recreate_database


@pytest.fixture(autouse=True)
def _fast_password_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(passwords, "BCRYPT_ROUNDS", 4)


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    await recreate_database(TEST_DATABASE_URL)
    # Alembic's async env runs its own event loop, so keep it off ours.
    await asyncio.to_thread(migrate, TEST_DATABASE_URL)
    eng = create_async_engine(TEST_DATABASE_URL)
    yield eng
    await eng.dispose()


@pytest.fixture
async def connection(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """A connection inside an outer transaction that is rolled back after the test."""
    async with engine.connect() as conn:
        outer = await conn.begin()
        yield conn
        await outer.rollback()


@pytest.fixture
async def db_session(connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    # Commits inside the test only release a savepoint; nothing outlives the test.
    session = AsyncSession(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    yield session
    await session.close()


@pytest.fixture(autouse=True)
async def _clean_rate_limits() -> None:
    """Rate-limit counters live in Redis, so clear them to keep tests independent."""
    redis = get_redis_client()
    keys = [key async for key in redis.scan_iter("ratelimit:*")]
    if keys:
        await redis.delete(*keys)


@pytest.fixture
def app(db_session: AsyncSession) -> FastAPI:
    application = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        yield db_session

    application.dependency_overrides[get_session] = _session
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
