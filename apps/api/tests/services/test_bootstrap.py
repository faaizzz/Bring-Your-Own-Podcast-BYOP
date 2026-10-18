from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from byop import main as main_module
from byop.config import Settings
from byop.models import User
from byop.security.passwords import verify_password
from byop.services.bootstrap import ensure_admin_user


def make_settings(email: str = "admin@example.com", password: str | None = "pw-12345") -> Settings:
    return Settings(
        byop_secret_key=SecretStr("k" * 32),
        byop_admin_email=email,
        byop_admin_password=SecretStr(password) if password is not None else None,
        _env_file=None,  # type: ignore[call-arg]  # pydantic-settings init kwarg, ignore any .env
    )


async def user_count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(User)) or 0


async def test_seeds_the_admin_with_a_hashed_password(db_session: AsyncSession) -> None:
    user = await ensure_admin_user(db_session, make_settings(email="  Admin@Example.COM "))

    assert user is not None
    assert user.email == "admin@example.com"
    assert user.is_admin and user.is_active
    assert user.password_hash != "pw-12345"
    assert verify_password("pw-12345", user.password_hash)


async def test_seeding_is_idempotent_and_never_overwrites(db_session: AsyncSession) -> None:
    first = await ensure_admin_user(db_session, make_settings(password="original-pw"))
    again = await ensure_admin_user(db_session, make_settings(password="changed-in-env"))

    assert first is not None and again is not None
    assert again.id == first.id
    assert await user_count(db_session) == 1
    assert verify_password("original-pw", again.password_hash)


async def test_no_password_means_no_seed(db_session: AsyncSession) -> None:
    assert await ensure_admin_user(db_session, make_settings(password=None)) is None
    assert await user_count(db_session) == 0


async def test_startup_seeds_the_admin(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    @asynccontextmanager
    async def _session() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(main_module, "get_settings", make_settings)
    monkeypatch.setattr(main_module, "get_sessionmaker", lambda: _session)
    app = main_module.create_app()

    async with app.router.lifespan_context(app):
        assert await user_count(db_session) == 1


async def test_startup_survives_an_unreachable_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dead = create_async_engine("postgresql+asyncpg://byop:byop@127.0.0.1:1/byop")
    monkeypatch.setattr(main_module, "get_settings", make_settings)
    monkeypatch.setattr(main_module, "get_sessionmaker", lambda: async_sessionmaker(dead))
    app = main_module.create_app()

    try:
        async with app.router.lifespan_context(app):
            pass  # reaching here means the failed seed did not crash startup
    finally:
        await dead.dispose()
