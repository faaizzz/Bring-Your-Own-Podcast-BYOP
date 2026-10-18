from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from byop.db import get_session
from byop.redis_client import get_redis


async def test_health_ok_when_dependencies_are_up(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


async def test_health_returns_503_when_postgres_is_down(app: FastAPI, client: AsyncClient) -> None:
    dead = create_async_engine("postgresql+asyncpg://byop:byop@127.0.0.1:1/byop")

    async def _dead_session() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(dead) as session:
            yield session

    app.dependency_overrides[get_session] = _dead_session
    try:
        response = await client.get("/api/health")
    finally:
        await dead.dispose()
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"] == "error"
    assert body["checks"]["redis"] == "ok"


async def test_health_returns_503_when_redis_is_down(app: FastAPI, client: AsyncClient) -> None:
    dead = Redis.from_url("redis://127.0.0.1:1/0", decode_responses=True)

    async def _dead_redis() -> AsyncIterator[Redis]:
        yield dead

    app.dependency_overrides[get_redis] = _dead_redis
    try:
        response = await client.get("/api/health")
    finally:
        await dead.aclose()
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "redis": "error"}


@pytest.mark.parametrize("path", ["/api/docs", "/api/openapi.json"])
async def test_api_docs_live_under_api_prefix(client: AsyncClient, path: str) -> None:
    assert (await client.get(path)).status_code == 200
