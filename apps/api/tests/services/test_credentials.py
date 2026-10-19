import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import ProviderCredential, User
from byop.models.enums import CredentialProvider as P
from byop.security.crypto import decrypt_json
from byop.services.credentials import (
    CredentialDecryptionError,
    CredentialResolver,
    ProviderNotConfigured,
    mask_secret,
    rotate_credentials,
)
from byop.services.provider_ref import ProviderRef
from tests.helpers import TEST_SECRET, make_settings
from tests.models.factories import make_user

USER_KEY = "sk-user-override-1111"
ENV_KEY = "sk-from-environment-2222"


async def save(
    resolver: CredentialResolver, user: User, provider: P = P.OPENAI, **kw: object
) -> None:
    args: dict[str, object] = {
        "api_key": USER_KEY,
        "base_url": None,
        "extra": None,
        "enabled": True,
    }
    await resolver.save(user.id, provider, **{**args, **kw})  # type: ignore[arg-type]


async def test_user_override_wins_over_the_environment(
    db_session: AsyncSession, admin_user: User
) -> None:
    resolver = CredentialResolver(db_session, make_settings(openai_api_key=SecretStr(ENV_KEY)))
    await save(resolver, admin_user)

    config = await resolver.get(admin_user.id, P.OPENAI)

    assert config.source == "user"
    assert config.api_key is not None and config.api_key.get_secret_value() == USER_KEY


async def test_environment_is_the_fallback(db_session: AsyncSession, admin_user: User) -> None:
    resolver = CredentialResolver(db_session, make_settings(openai_api_key=SecretStr(ENV_KEY)))

    config = await resolver.get(admin_user.id, P.OPENAI)

    assert config.source == "env"
    assert config.api_key is not None and config.api_key.get_secret_value() == ENV_KEY


async def test_not_configured_anywhere_raises(db_session: AsyncSession, admin_user: User) -> None:
    resolver = CredentialResolver(db_session, make_settings())

    with pytest.raises(ProviderNotConfigured) as excinfo:
        await resolver.get(admin_user.id, P.ELEVENLABS)

    assert excinfo.value.provider is P.ELEVENLABS


async def test_disabled_override_falls_back_to_the_environment(
    db_session: AsyncSession, admin_user: User
) -> None:
    resolver = CredentialResolver(db_session, make_settings(openai_api_key=SecretStr(ENV_KEY)))
    await save(resolver, admin_user, enabled=False)

    assert (await resolver.get(admin_user.id, P.OPENAI)).source == "env"


async def test_disabled_override_without_environment_is_not_configured(
    db_session: AsyncSession, admin_user: User
) -> None:
    resolver = CredentialResolver(db_session, make_settings())
    await save(resolver, admin_user, enabled=False)

    with pytest.raises(ProviderNotConfigured):
        await resolver.get(admin_user.id, P.OPENAI)


async def test_deleting_the_override_restores_the_environment(
    db_session: AsyncSession, admin_user: User
) -> None:
    resolver = CredentialResolver(db_session, make_settings(openai_api_key=SecretStr(ENV_KEY)))
    await save(resolver, admin_user)
    await resolver.delete(admin_user.id, P.OPENAI)

    assert (await resolver.get(admin_user.id, P.OPENAI)).source == "env"


async def test_overrides_are_private_to_their_user(
    db_session: AsyncSession, admin_user: User
) -> None:
    other = await make_user(db_session, "other@example.com")
    resolver = CredentialResolver(db_session, make_settings())
    await save(resolver, admin_user)

    with pytest.raises(ProviderNotConfigured):
        await resolver.get(other.id, P.OPENAI)


async def test_secret_is_encrypted_at_rest(db_session: AsyncSession, admin_user: User) -> None:
    resolver = CredentialResolver(db_session, make_settings())
    await save(resolver, admin_user, base_url="https://proxy.example/v1", extra={"org": "acme"})

    stored = (await db_session.scalars(select(ProviderCredential))).one()

    assert USER_KEY not in stored.secret_encrypted
    assert decrypt_json(stored.secret_encrypted, SecretStr(TEST_SECRET)) == {
        "api_key": USER_KEY,
        "base_url": "https://proxy.example/v1",
        "extra": {"org": "acme"},
    }


async def test_omitted_fields_keep_their_stored_value(
    db_session: AsyncSession, admin_user: User
) -> None:
    resolver = CredentialResolver(db_session, make_settings())
    await save(resolver, admin_user, base_url="https://proxy.example/v1")

    await save(resolver, admin_user, api_key=None, base_url=None, enabled=False)

    stored = (await db_session.scalars(select(ProviderCredential))).one()
    assert decrypt_json(stored.secret_encrypted, SecretStr(TEST_SECRET))["api_key"] == USER_KEY
    assert stored.enabled is False


async def test_langfuse_env_combines_both_keys_and_host(
    db_session: AsyncSession, admin_user: User
) -> None:
    only_public = CredentialResolver(
        db_session, make_settings(langfuse_public_key=SecretStr("pk-lf-1"))
    )
    with pytest.raises(ProviderNotConfigured):
        await only_public.get(admin_user.id, P.LANGFUSE)

    both = CredentialResolver(
        db_session,
        make_settings(
            langfuse_public_key=SecretStr("pk-lf-1"),
            langfuse_secret_key=SecretStr("sk-lf-2"),
            langfuse_host="https://lf.example",
        ),
    )
    config = await both.get(admin_user.id, P.LANGFUSE)
    assert config.base_url == "https://lf.example"
    assert config.extra == {"public_key": "pk-lf-1"}
    assert config.api_key is not None and config.api_key.get_secret_value() == "sk-lf-2"


async def test_kokoro_needs_a_base_url_not_a_key(
    db_session: AsyncSession, admin_user: User
) -> None:
    resolver = CredentialResolver(
        db_session, make_settings(kokoro_base_url="http://kokoro:8880/v1")
    )

    config = await resolver.get(admin_user.id, P.KOKORO)

    assert (config.source, config.base_url, config.api_key) == (
        "env",
        "http://kokoro:8880/v1",
        None,
    )


async def test_view_masks_everything_secret(db_session: AsyncSession, admin_user: User) -> None:
    resolver = CredentialResolver(db_session, make_settings())
    await save(resolver, admin_user, extra={"public_key": "pk-lf-abcdef123456"})

    view = await resolver.view(admin_user.id, P.OPENAI)

    assert view.api_key_masked == "sk-…1111"
    assert view.extra_masked == {"public_key": "pk-…3456"}
    assert USER_KEY not in repr(view)


async def test_view_reports_none_when_nothing_is_set(
    db_session: AsyncSession, admin_user: User
) -> None:
    view = await CredentialResolver(db_session, make_settings()).view(admin_user.id, P.OPENROUTER)

    assert (view.source, view.api_key_masked) == ("none", None)


async def test_unreadable_secret_is_reported_not_leaked(
    db_session: AsyncSession, admin_user: User
) -> None:
    await save(CredentialResolver(db_session, make_settings()), admin_user)
    rotated = CredentialResolver(db_session, make_settings(byop_secret_key=SecretStr("z" * 32)))

    view = await rotated.view(admin_user.id, P.OPENAI)
    with pytest.raises(CredentialDecryptionError, match="rotate-key"):
        await rotated.get(admin_user.id, P.OPENAI)

    assert view.source == "user" and view.problem is not None and view.api_key_masked is None


def test_mask_secret() -> None:
    assert mask_secret("sk-or-v1-abcdef1234") == "sk-…1234"
    assert mask_secret("short") == "••••"
    assert mask_secret("12345678") == "••••"
    assert mask_secret("123456789") == "123…6789"


async def test_rotation_reencrypts_everything_under_the_new_key(
    db_session: AsyncSession, admin_user: User
) -> None:
    old, new = SecretStr(TEST_SECRET), SecretStr("n" * 32)
    resolver = CredentialResolver(db_session, make_settings())
    await save(resolver, admin_user, P.OPENAI)
    await save(resolver, admin_user, P.OPENROUTER, api_key="sk-or-other-key-9999")

    assert await rotate_credentials(db_session, old, new) == 2

    after = CredentialResolver(db_session, make_settings(byop_secret_key=new))
    assert (await after.get(admin_user.id, P.OPENAI)).api_key == SecretStr(USER_KEY)
    assert (await after.get(admin_user.id, P.OPENROUTER)).api_key == SecretStr(
        "sk-or-other-key-9999"
    )


async def test_rotation_with_the_wrong_old_key_changes_nothing(
    db_session: AsyncSession, admin_user: User
) -> None:
    await save(CredentialResolver(db_session, make_settings()), admin_user)
    before = (await db_session.scalars(select(ProviderCredential))).one().secret_encrypted

    with pytest.raises(CredentialDecryptionError):
        await rotate_credentials(db_session, SecretStr("w" * 32), SecretStr("n" * 32))

    after = (await db_session.scalars(select(ProviderCredential))).one().secret_encrypted
    assert after == before


async def test_rotation_covers_connections_too(db_session: AsyncSession, admin_user: User) -> None:
    from tests.models.factories import make_connection

    old, new = SecretStr(TEST_SECRET), SecretStr("n" * 32)
    conn = await make_connection(
        db_session, admin_user, api_key="sk-conn-key-123456", headers={"X-A": "secret-value"}
    )

    assert await rotate_credentials(db_session, old, new) == 1

    after = CredentialResolver(db_session, make_settings(byop_secret_key=new))
    config = await after.get_ref(admin_user.id, ProviderRef(connection_id=conn.id), "llm")
    assert config.api_key == SecretStr("sk-conn-key-123456")
    assert config.headers == {"X-A": "secret-value"}


async def test_a_connection_must_exist_be_enabled_and_allow_the_use(
    db_session: AsyncSession, admin_user: User
) -> None:
    from tests.models.factories import make_connection, make_user

    resolver = CredentialResolver(db_session, make_settings())
    voices = await make_connection(db_session, admin_user, "V", llm=False, tts=True)
    off = await make_connection(db_session, admin_user, "Off", enabled=False)
    other = await make_connection(db_session, await make_user(db_session, "o@example.com"), "O")

    assert (
        await resolver.get_ref(admin_user.id, ProviderRef(connection_id=voices.id), "tts")
    ).label == "V"
    for record, use, message in (
        (voices, "llm", "not enabled for language models"),
        (off, "llm", "disabled"),
        (other, "llm", "does not exist"),
    ):
        with pytest.raises(ProviderNotConfigured, match=message):
            await resolver.get_ref(admin_user.id, ProviderRef(connection_id=record.id), use)  # type: ignore[arg-type]
    with pytest.raises(ProviderNotConfigured, match="not enabled for voices"):
        await resolver.get_ref(
            admin_user.id,
            ProviderRef(connection_id=(await make_connection(db_session, admin_user, "L")).id),
            "tts",
        )
