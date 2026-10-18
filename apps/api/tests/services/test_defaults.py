import httpx
import pytest
import respx
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import User
from byop.models.enums import CredentialProvider as P
from byop.services.credentials import CredentialResolver
from byop.services.defaults import default_tts_provider
from tests.helpers import make_settings

KOKORO = "http://kokoro:8880/v1"


def resolver(session: AsyncSession, **settings: object) -> CredentialResolver:
    return CredentialResolver(session, make_settings(**settings))


async def test_nothing_configured_means_no_default(
    db_session: AsyncSession, admin_user: User
) -> None:
    assert await default_tts_provider(resolver(db_session), admin_user.id) is None


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({"elevenlabs_api_key": SecretStr("xi-1")}, P.ELEVENLABS),
        ({"openai_api_key": SecretStr("sk-1")}, P.OPENAI),
        ({"openrouter_api_key": SecretStr("sk-or-1")}, P.OPENROUTER),
        # preference order when several paid keys exist
        (
            {"openai_api_key": SecretStr("sk-1"), "openrouter_api_key": SecretStr("sk-or-1")},
            P.OPENAI,
        ),
        (
            {"elevenlabs_api_key": SecretStr("xi-1"), "openai_api_key": SecretStr("sk-1")},
            P.ELEVENLABS,
        ),
    ],
)
async def test_a_configured_paid_provider_is_preferred(
    db_session: AsyncSession, admin_user: User, settings: dict[str, object], expected: P
) -> None:
    assert await default_tts_provider(resolver(db_session, **settings), admin_user.id) is expected


@respx.mock
async def test_paid_providers_win_over_a_running_kokoro(
    db_session: AsyncSession, admin_user: User
) -> None:
    kokoro = respx.get(f"{KOKORO}/audio/voices").respond(200, json={"voices": []})

    chosen = await default_tts_provider(
        resolver(db_session, openai_api_key=SecretStr("sk-1"), kokoro_base_url=KOKORO),
        admin_user.id,
    )

    assert chosen is P.OPENAI
    assert not kokoro.called  # no need to probe Kokoro


@respx.mock
async def test_kokoro_is_the_default_when_no_paid_key_exists_and_it_is_running(
    db_session: AsyncSession, admin_user: User
) -> None:
    respx.get(f"{KOKORO}/audio/voices").respond(200, json={"voices": ["af_bella"]})

    chosen = await default_tts_provider(resolver(db_session, kokoro_base_url=KOKORO), admin_user.id)

    assert chosen is P.KOKORO


@respx.mock
async def test_a_configured_but_stopped_kokoro_is_not_preselected(
    db_session: AsyncSession, admin_user: User
) -> None:
    respx.get(f"{KOKORO}/audio/voices").mock(side_effect=httpx.ConnectError("down"))

    chosen = await default_tts_provider(resolver(db_session, kokoro_base_url=KOKORO), admin_user.id)

    assert chosen is None


@respx.mock
async def test_a_user_override_counts_as_configured(
    db_session: AsyncSession, admin_user: User
) -> None:
    res = resolver(db_session)
    await res.save(
        admin_user.id,
        P.ELEVENLABS,
        api_key="xi-user-key-1234567",
        base_url=None,
        extra=None,
        enabled=True,
    )

    assert await default_tts_provider(res, admin_user.id) is P.ELEVENLABS
