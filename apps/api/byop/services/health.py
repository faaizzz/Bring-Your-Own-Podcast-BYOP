import asyncio
from collections.abc import Awaitable

import structlog
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from byop.schemas.health import CheckStatus, HealthResponse

CHECK_TIMEOUT_SECONDS = 3.0

log = structlog.get_logger(__name__)


async def _probe(name: str, check: Awaitable[object]) -> CheckStatus:
    try:
        await asyncio.wait_for(check, CHECK_TIMEOUT_SECONDS)
    except Exception as exc:
        log.warning("health_check_failed", check=name, error=type(exc).__name__)
        return "error"
    return "ok"


async def _ping(redis: Redis) -> None:
    await redis.ping()


async def check_health(session: AsyncSession, redis: Redis) -> HealthResponse:
    """Probe Postgres and Redis; any failing dependency marks the service degraded."""
    db_status, redis_status = await asyncio.gather(
        _probe("database", session.execute(text("SELECT 1"))),
        _probe("redis", _ping(redis)),
    )
    checks: dict[str, CheckStatus] = {"database": db_status, "redis": redis_status}
    if all(v == "ok" for v in checks.values()):
        return HealthResponse(status="ok", checks=checks)
    return HealthResponse(status="degraded", checks=checks)
