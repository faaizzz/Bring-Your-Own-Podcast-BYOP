import os
from pathlib import Path

from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://byop:byop@localhost:5432/byop_test"
)
API_ROOT = Path(__file__).resolve().parent.parent


async def recreate_database(url: str) -> None:
    """Drop and create the database so a test starts from migrations alone."""
    parsed = make_url(url)
    admin = create_async_engine(parsed.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{parsed.database}" WITH (FORCE)'))
            await conn.execute(text(f'CREATE DATABASE "{parsed.database}"'))
    finally:
        await admin.dispose()


def migrate(url: str, revision: str = "head", *, downgrade: bool = False) -> None:
    """Run Alembic against `url`. Synchronous: its async env owns an event loop."""
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    (command.downgrade if downgrade else command.upgrade)(cfg, revision)
