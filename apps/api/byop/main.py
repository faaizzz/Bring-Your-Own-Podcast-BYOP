from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from byop.api import api_router
from byop.config import get_settings
from byop.db import dispose_engine, get_sessionmaker
from byop.logging import configure_logging, install_request_logging
from byop.redis_client import close_redis
from byop.services.bootstrap import ensure_admin_user


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    log = structlog.get_logger("byop")
    log.info("startup")
    try:
        async with get_sessionmaker()() as session:
            await ensure_admin_user(session, get_settings())
    except Exception:
        # The API must still start (and report 503 on /api/health) when the database is
        # down or not migrated yet; seeding is retried on the next start.
        log.exception("admin_seed_failed", hint="is the database up and migrated (make migrate)?")
    yield
    await dispose_engine()
    await close_redis()


def create_app() -> FastAPI:
    settings = get_settings()  # fails fast with a readable message when misconfigured
    configure_logging(settings.log_level)
    app = FastAPI(
        title="BYOP",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    install_request_logging(app)
    app.include_router(api_router)
    return app


app = create_app()
