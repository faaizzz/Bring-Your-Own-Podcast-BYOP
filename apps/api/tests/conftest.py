import asyncio
import os
import socket
from collections.abc import AsyncIterator, Iterator

# Settings are validated at import time, so the test environment must exist first.
os.environ["BYOP_SECRET_KEY"] = "test-secret-key-0123456789abcdef"  # keep in sync with TEST_SECRET
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
# Keep tests hermetic: a developer's real provider keys must never leak into settings.
os.environ.pop("OPENROUTER_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("ELEVENLABS_API_KEY", None)
os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
os.environ.pop("LANGFUSE_SECRET_KEY", None)
os.environ.pop("LANGFUSE_HOST", None)
os.environ.pop("KOKORO_BASE_URL", None)
os.environ.pop("BYOP_ADMIN_PASSWORD", None)

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine

from byop.db import get_session
from byop.main import create_app
from byop.models import User
from byop.redis_client import get_redis_client
from byop.security import passwords
from byop.security.tokens import COOKIE_NAME, create_session_token
from tests.db_utils import TEST_DATABASE_URL, migrate, recreate_database
from tests.models.factories import make_user


@pytest.fixture(autouse=True, scope="session")
def _block_external_network() -> Iterator[None]:
    """Tests may talk to local Postgres/Redis only; anything else must be mocked (respx)."""
    real_connect = socket.socket.connect

    def guarded(self: socket.socket, address: object) -> None:
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost") and not str(host).startswith("/"):
            raise RuntimeError(
                f"Network access to {host!r} is blocked in tests; mock it with respx"
            )
        real_connect(self, address)  # type: ignore[arg-type]

    socket.socket.connect = guarded  # type: ignore[method-assign,assignment]
    yield
    socket.socket.connect = real_connect  # type: ignore[method-assign]


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
    """Rate-limit counters and cached model lists live in Redis; clear them between tests."""
    redis = get_redis_client()
    for pattern in ("ratelimit:*", "models:*", "voices:*", "discovery:*"):
        keys = [key async for key in redis.scan_iter(pattern)]
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


TEST_SECRET = "test-secret-key-0123456789abcdef"


@pytest.fixture
async def admin_user(db_session: AsyncSession) -> User:
    user = await make_user(db_session, "admin@example.com")
    user.password_hash = passwords.hash_password("correct-horse-battery")
    await db_session.flush()
    return user


@pytest.fixture
async def authed(client: AsyncClient, admin_user: User) -> AsyncClient:
    """The shared client with a valid session cookie for `admin_user`."""
    token = create_session_token(
        admin_user.id, admin_user.password_hash, SecretStr(TEST_SECRET), ttl_hours=1
    )
    client.cookies.set(COOKIE_NAME, token)
    return client


PUBLIC_IP = "93.184.216.34"
PRIVATE_HOSTS = {"internal.example": ["10.0.0.5"], "metadata.example": ["169.254.169.254"]}


@pytest.fixture
def fake_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve every hostname to a public address (except the PRIVATE_HOSTS), without real DNS."""
    from byop.services import safe_http
    from byop.services.safe_http import FetchError

    async def resolve(host: str, port: int) -> list[str]:
        if host in PRIVATE_HOSTS:
            return PRIVATE_HOSTS[host]
        if host.replace(".", "").isdigit():
            return [host]
        if host.endswith(".invalid"):
            raise FetchError(f"Could not find the host '{host}'")
        return [PUBLIC_IP]

    monkeypatch.setattr(safe_http, "resolve_host", resolve)
