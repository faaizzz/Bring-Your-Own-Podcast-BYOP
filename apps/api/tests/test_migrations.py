import asyncio
import uuid

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from byop.models import Base
from byop.security.crypto import decrypt_json, encrypt_json
from tests.db_utils import TEST_DATABASE_URL, migrate, recreate_database
from tests.helpers import TEST_SECRET

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
    "provider_connections",
    "user_settings",
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


# --- 0011: provider connections -------------------------------------------------------------------

SECRET = SecretStr(TEST_SECRET)


async def _seed_v010(conn: AsyncConnection, *, credential_token: str) -> uuid.UUID:
    """A v0.1.0 database: one user whose shows use the old `openai_compatible` credential."""
    user_id = uuid.uuid4()
    await conn.execute(
        text("INSERT INTO users (id, email, password_hash) VALUES (:id, 'a@example.com', 'x')"),
        {"id": user_id},
    )
    await conn.execute(
        text(
            "INSERT INTO provider_credentials (user_id, provider, secret_encrypted, enabled) "
            "VALUES (:u, 'openai_compatible', :token, true)"
        ),
        {"u": user_id, "token": credential_token},
    )
    for slug, provider in (("a", "openai_compatible"), ("b", "openai")):
        await conn.execute(
            text(
                "INSERT INTO shows (user_id, title, slug, topic, llm_provider, llm_model) "
                "VALUES (:u, :slug, :slug, 't', :p, 'm')"
            ),
            {"u": user_id, "slug": slug, "p": provider},
        )
    show_id = await conn.scalar(text("SELECT id FROM shows WHERE slug = 'a'"))
    await conn.execute(
        text(
            "INSERT INTO speakers (user_id, show_id, position, name, tts_provider, voice_id) "
            "VALUES (:u, :s, 0, 'Alex', 'kokoro', 'af_bella')"
        ),
        {"u": user_id, "s": show_id},
    )
    return user_id


async def test_upgrade_moves_the_openai_compatible_credential_into_a_connection(
    empty_db: str,
) -> None:
    await asyncio.to_thread(migrate, empty_db, "0010")
    token = encrypt_json(
        {"api_key": "sk-local-1234567890", "base_url": "http://ollama:11434/v1", "extra": {}},
        SECRET,
    )
    engine = create_async_engine(empty_db)
    try:
        async with engine.begin() as conn:
            user_id = await _seed_v010(conn, credential_token=token)

        await asyncio.to_thread(migrate, empty_db)

        async with engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text("SELECT * FROM provider_connections WHERE user_id = :u"),
                        {"u": user_id},
                    )
                )
                .mappings()
                .one()
            )
            assert (row["name"], row["base_url"]) == ("OpenAI-compatible", "http://ollama:11434/v1")
            assert (row["llm"], row["tts"], row["enabled"]) == (True, False, True)
            # The key survived, in the new document shape.
            assert decrypt_json(row["secret_encrypted"], SECRET) == {
                "api_key": "sk-local-1234567890",
                "headers": [],
            }
            # Shows were repointed; other providers and speakers were left alone.
            refs: dict[str, str] = dict(
                (await conn.execute(text("SELECT slug, llm_provider FROM shows"))).all()
            )
            assert refs == {"a": f"conn:{row['id']}", "b": "openai"}
            assert await conn.scalar(text("SELECT tts_provider FROM speakers")) == "kokoro"
            # The single credential is gone.
            assert await conn.scalar(text("SELECT count(*) FROM provider_credentials")) == 0
    finally:
        await engine.dispose()


async def test_an_unreadable_old_credential_becomes_a_disabled_connection(empty_db: str) -> None:
    await asyncio.to_thread(migrate, empty_db, "0010")
    foreign = encrypt_json({"base_url": "http://x/v1"}, SecretStr("another-secret-key-0123456789"))
    engine = create_async_engine(empty_db)
    try:
        async with engine.begin() as conn:
            await _seed_v010(conn, credential_token=foreign)

        await asyncio.to_thread(migrate, empty_db)

        async with engine.connect() as conn:
            enabled = await conn.scalar(text("SELECT enabled FROM provider_connections"))
            ref = await conn.scalar(text("SELECT llm_provider FROM shows WHERE slug = 'a'"))
        assert enabled is False  # the user fixes the URL; the show still points at it
        assert str(ref).startswith("conn:")
    finally:
        await engine.dispose()


async def test_downgrade_restores_the_single_credential(empty_db: str) -> None:
    await asyncio.to_thread(migrate, empty_db, "0010")
    token = encrypt_json({"api_key": None, "base_url": "http://ollama:11434/v1"}, SECRET)
    engine = create_async_engine(empty_db)
    try:
        async with engine.begin() as conn:
            await _seed_v010(conn, credential_token=token)
        await asyncio.to_thread(migrate, empty_db)
        await asyncio.to_thread(migrate, empty_db, "0010", downgrade=True)

        async with engine.connect() as conn:
            assert "provider_connections" not in await _tables(conn)
            stored = await conn.scalar(
                text("SELECT secret_encrypted FROM provider_credentials WHERE provider = :p"),
                {"p": "openai_compatible"},
            )
            assert decrypt_json(str(stored), SECRET)["base_url"] == "http://ollama:11434/v1"
            ref = await conn.scalar(text("SELECT llm_provider FROM shows WHERE slug = 'a'"))
            assert ref == "openai_compatible"
    finally:
        await engine.dispose()


# --- 0012: user settings --------------------------------------------------------------------------


async def test_upgrade_from_0011_adds_user_settings_and_keeps_everything_else(
    empty_db: str,
) -> None:
    await asyncio.to_thread(migrate, empty_db, "0011")
    token = encrypt_json({"api_key": None, "headers": []}, SECRET)
    engine = create_async_engine(empty_db)
    try:
        async with engine.begin() as conn:
            user_id = await _seed_v010_shape(conn, token)

        await asyncio.to_thread(migrate, empty_db)

        async with engine.connect() as conn:
            assert "user_settings" in await _tables(conn)
            assert await conn.scalar(text("SELECT count(*) FROM user_settings")) == 0
            refs = (await conn.execute(text("SELECT slug, llm_provider FROM shows"))).all()
            assert sorted(tuple(r) for r in refs) == [("a", "openrouter"), ("b", "openai")]
            assert await conn.scalar(text("SELECT count(*) FROM speakers")) == 1
            # A row can be saved for the existing user, once.
            await conn.execute(
                text(
                    "INSERT INTO user_settings (user_id, discovery_llm_provider, "
                    "discovery_llm_model) VALUES (:u, 'openrouter', 'perplexity/sonar')"
                ),
                {"u": user_id},
            )
            with pytest.raises(Exception, match="uq_user_settings_user_id"):
                await conn.execute(
                    text("INSERT INTO user_settings (user_id) VALUES (:u)"), {"u": user_id}
                )
    finally:
        await engine.dispose()


async def _seed_v010_shape(conn: AsyncConnection, _token: str) -> uuid.UUID:
    """A user with two shows and a speaker, as an existing installation has."""
    user_id = uuid.uuid4()
    await conn.execute(
        text("INSERT INTO users (id, email, password_hash) VALUES (:id, 'a@example.com', 'x')"),
        {"id": user_id},
    )
    for slug, provider in (("a", "openrouter"), ("b", "openai")):
        await conn.execute(
            text(
                "INSERT INTO shows (user_id, title, slug, topic, llm_provider, llm_model) "
                "VALUES (:u, :slug, :slug, 't', :p, 'm')"
            ),
            {"u": user_id, "slug": slug, "p": provider},
        )
    show_id = await conn.scalar(text("SELECT id FROM shows WHERE slug = 'a'"))
    await conn.execute(
        text(
            "INSERT INTO speakers (user_id, show_id, position, name, tts_provider, voice_id) "
            "VALUES (:u, :s, 0, 'Alex', 'kokoro', 'af_bella')"
        ),
        {"u": user_id, "s": show_id},
    )
    return user_id


async def test_downgrade_from_0012_drops_the_table(empty_db: str) -> None:
    await asyncio.to_thread(migrate, empty_db)
    await asyncio.to_thread(migrate, empty_db, "0011", downgrade=True)

    engine = create_async_engine(empty_db)
    try:
        async with engine.connect() as conn:
            assert "user_settings" not in await _tables(conn)
    finally:
        await engine.dispose()


# --- 0013: delay between requests ---------------------------------------------------------


async def test_upgrade_from_0012_adds_the_wait_settings_without_changing_anything(
    empty_db: str,
) -> None:
    await asyncio.to_thread(migrate, empty_db, "0012")
    engine = create_async_engine(empty_db)
    try:
        async with engine.begin() as conn:
            user_id = await _seed_v010_shape(conn, "")
            await conn.execute(
                text(
                    "INSERT INTO provider_connections (user_id, name, base_url, secret_encrypted) "
                    "VALUES (:u, 'Box', 'http://box/v1', 'x')"
                ),
                {"u": user_id},
            )
            await conn.execute(
                text(
                    "INSERT INTO user_settings (user_id, discovery_llm_provider, "
                    "discovery_llm_model) VALUES (:u, 'openrouter', 'perplexity/sonar')"
                ),
                {"u": user_id},
            )

        await asyncio.to_thread(migrate, empty_db)

        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT min_interval_s FROM provider_connections")) == 0
            row = (await conn.execute(text("SELECT * FROM user_settings"))).mappings().one()
            assert row["request_intervals"] == {}
            assert row["discovery_llm_model"] == "perplexity/sonar"  # the earlier setting survived
            assert await conn.scalar(text("SELECT count(*) FROM shows")) == 2
    finally:
        await engine.dispose()
