import asyncio

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from byop.models import Base
from tests.db_utils import TEST_DATABASE_URL, migrate, recreate_database

MIGRATION_DB = make_url(TEST_DATABASE_URL).set(database="byop_migration_test")
EXPECTED_TABLES = {
    "users",
    "provider_credentials",
    "shows",
    "speakers",
    "sources",
    "items",
    "runs",
    "run_events",
    "episodes",
    "usage_events",
    "price_overrides",
}


async def _tables(conn: AsyncConnection) -> set[str]:
    rows = await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
    return {r[0] for r in rows} - {"alembic_version"}


async def _has_extension(conn: AsyncConnection, name: str) -> bool:
    found = await conn.scalar(text("SELECT 1 FROM pg_extension WHERE extname = :n"), {"n": name})
    return bool(found == 1)


@pytest.fixture
async def empty_db() -> str:
    url = MIGRATION_DB.render_as_string(hide_password=False)
    await recreate_database(url)
    return url


async def test_upgrade_from_empty_creates_the_schema_without_drift(empty_db: str) -> None:
    await asyncio.to_thread(migrate, empty_db)

    engine = create_async_engine(empty_db)
    try:
        async with engine.connect() as conn:
            assert await _tables(conn) == EXPECTED_TABLES
            assert await _has_extension(conn, "pg_trgm")
            # The models and the migration must describe the same schema.
            diff = await conn.run_sync(
                lambda sync_conn: compare_metadata(
                    MigrationContext.configure(sync_conn), Base.metadata
                )
            )
            assert diff == []
    finally:
        await engine.dispose()


async def test_downgrade_to_base_removes_everything_and_upgrade_works_again(empty_db: str) -> None:
    await asyncio.to_thread(migrate, empty_db)
    await asyncio.to_thread(migrate, empty_db, "base", downgrade=True)

    engine = create_async_engine(empty_db)
    try:
        async with engine.connect() as conn:
            assert await _tables(conn) == set()
            assert not await _has_extension(conn, "pg_trgm")
        await asyncio.to_thread(migrate, empty_db)
        async with engine.connect() as conn:
            assert await _tables(conn) == EXPECTED_TABLES
    finally:
        await engine.dispose()
