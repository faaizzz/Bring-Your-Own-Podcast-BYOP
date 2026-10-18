from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from byop import cli
from byop.models import User
from byop.models.enums import CredentialProvider as P
from byop.services.credentials import CredentialResolver
from tests.helpers import make_settings


@pytest.fixture
def cli_db(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncSession:
    """Point the CLI at the per-test transaction instead of the real database."""

    @asynccontextmanager
    async def _session() -> AsyncIterator[AsyncSession]:
        yield db_session

    async def _no_dispose() -> None:
        return None

    monkeypatch.setattr(cli, "get_sessionmaker", lambda: _session)
    monkeypatch.setattr(cli, "dispose_engine", _no_dispose)
    return db_session


def test_rotate_key_needs_the_old_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(cli.OLD_KEY_ENV, raising=False)

    assert cli.main(["rotate-key"]) == 2
    assert cli.OLD_KEY_ENV in capsys.readouterr().err


async def test_rotate_key_moves_credentials_to_the_current_key(
    cli_db: AsyncSession, admin_user: User, capsys: pytest.CaptureFixture[str]
) -> None:
    old = "o" * 32
    await CredentialResolver(cli_db, make_settings(byop_secret_key=SecretStr(old))).save(
        admin_user.id,
        P.OPENAI,
        api_key="sk-cli-test-key-0000",
        base_url=None,
        extra=None,
        enabled=True,
    )

    assert await cli._rotate_key(old) == 0

    assert "Re-encrypted 1" in capsys.readouterr().out
    current = CredentialResolver(cli_db, make_settings())  # the key the app runs with now
    assert (await current.get(admin_user.id, P.OPENAI)).api_key == SecretStr("sk-cli-test-key-0000")


async def test_rotate_key_aborts_cleanly_with_the_wrong_old_key(
    cli_db: AsyncSession, admin_user: User, capsys: pytest.CaptureFixture[str]
) -> None:
    await CredentialResolver(cli_db, make_settings()).save(
        admin_user.id,
        P.OPENAI,
        api_key="sk-cli-test-key-0000",
        base_url=None,
        extra=None,
        enabled=True,
    )

    assert await cli._rotate_key("w" * 32) == 1

    assert "nothing changed" in capsys.readouterr().err
