import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
import respx
import structlog
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import get_settings
from byop.models import RunEvent, User
from byop.models.enums import CredentialProvider, RunStatus
from byop.pipeline.context import RunContext
from byop.pipeline.orchestrator import Stage, run_stage
from byop.providers.common import RetryPolicy, record_notice
from byop.providers.llm import get_llm
from byop.providers.llm.base import Message
from byop.providers.tts import get_tts
from byop.services.credentials import CredentialResolver, ProviderConfig
from byop.services.provider_ref import ProviderRef
from byop.services.runs import create_run
from byop.services.throttle import MAX_INTERVAL_S, RequestThrottle, throttle_for
from byop.services.user_settings import request_interval, request_intervals, save_request_interval
from tests.helpers import make_settings
from tests.models.factories import make_connection, make_show, make_user
from tests.providers.llm.helpers import OPENROUTER_URL, completion
from tests.providers.tts.helpers import FAST_RETRY, pcm_bytes

REDIS_URL = get_settings().redis_url


@pytest.fixture
async def key() -> AsyncIterator[str]:
    name = f"throttle:test:{uuid.uuid4()}"
    yield name
    redis = Redis.from_url(REDIS_URL)
    await redis.delete(name)
    await redis.aclose()


def throttle(key: str, interval: float, notes: list[str] | None = None) -> RequestThrottle:
    return RequestThrottle(
        key=key,
        interval_s=interval,
        label="OpenRouter",
        redis_url=REDIS_URL,
        notify=(notes.append if notes is not None else (lambda _: None)),
    )


async def starts(t: RequestThrottle, count: int) -> list[float]:
    """When each of `count` concurrent callers is let through."""
    began = time.monotonic()

    async def one() -> float:
        await t.wait()
        return time.monotonic() - began

    return sorted(await asyncio.gather(*(one() for _ in range(count))))


async def test_concurrent_calls_start_at_least_the_interval_apart(key: str) -> None:
    times = await starts(throttle(key, 0.3), 3)

    assert times[0] < 0.2  # the first goes straight through
    assert times[1] - times[0] >= 0.28
    assert times[2] - times[1] >= 0.28


async def test_two_throttles_on_the_same_key_share_the_queue(key: str) -> None:
    """Workers each build their own: what they share is the Redis key."""
    first, second = throttle(key, 0.3), throttle(key, 0.3)
    began = time.monotonic()

    async def after(t: RequestThrottle) -> float:
        await t.wait()
        return time.monotonic() - began

    a, b = sorted(await asyncio.gather(after(first), after(second)))

    assert b - a >= 0.28


async def test_a_call_after_the_interval_is_not_delayed(key: str) -> None:
    t = throttle(key, 0.2)
    await t.wait()
    await asyncio.sleep(0.25)

    assert await t.wait() == 0.0


async def test_other_providers_are_not_slowed(key: str) -> None:
    slow = throttle(key, 1.0)
    other = throttle(key + ":other", 1.0)
    await slow.wait()

    began = time.monotonic()
    await other.wait()

    assert time.monotonic() - began < 0.2
    redis = Redis.from_url(REDIS_URL)
    await redis.delete(key + ":other")
    await redis.aclose()


async def test_a_wait_is_announced_in_the_run_log_but_a_tiny_one_is_not(key: str) -> None:
    notes: list[str] = []
    t = throttle(key, 0.6, notes)
    await t.wait()

    waited = await t.wait()

    assert 0.4 < waited <= 0.6
    assert len(notes) == 1 and notes[0].startswith("Waiting 0.") and "OpenRouter" in notes[0]
    assert "rate limit" in notes[0]

    short_notes: list[str] = []
    short = throttle(key + ":short", 0.1, short_notes)
    await short.wait()
    await short.wait()
    assert short_notes == []
    redis = Redis.from_url(REDIS_URL)
    await redis.delete(key + ":short")
    await redis.aclose()


async def test_calls_go_through_when_redis_is_down(key: str) -> None:
    t = RequestThrottle(
        key=key, interval_s=5, label="OpenRouter", redis_url="redis://127.0.0.1:1/0"
    )

    began = time.monotonic()
    with structlog.testing.capture_logs() as logs:
        waited = [await t.wait(), await t.wait()]

    assert waited == [0.0, 0.0] and time.monotonic() - began < 3
    assert any(e["event"] == "throttle_unavailable" and e["log_level"] == "warning" for e in logs)


# --- from a resolved provider -----------------------------------------------------------------


def config(
    *, min_interval_s: float = 0.0, throttle_key: str | None = None, label: str | None = None
) -> ProviderConfig:
    return ProviderConfig(
        CredentialProvider.OPENROUTER,
        "env",
        api_key=SecretStr("sk-or-test-12345678"),
        label=label,
        min_interval_s=min_interval_s,
        throttle_key=throttle_key,
    )


def test_a_provider_without_a_wait_has_no_throttle() -> None:
    assert throttle_for(config()) is None
    assert throttle_for(config(min_interval_s=0.0, throttle_key="throttle:u:openrouter")) is None
    assert throttle_for(config(min_interval_s=5.0)) is None  # no key to queue on


def test_the_throttle_is_named_after_the_provider_or_connection_and_capped() -> None:
    builtin = throttle_for(config(min_interval_s=5.0, throttle_key="throttle:u:openrouter"))
    named = throttle_for(
        config(min_interval_s=500.0, throttle_key="throttle:u:conn:1", label="Home Ollama")
    )

    assert isinstance(builtin, RequestThrottle) and isinstance(named, RequestThrottle)
    assert (builtin.label, builtin.interval_s, builtin.key) == (
        "OpenRouter",
        5.0,
        "throttle:u:openrouter",
    )
    assert (named.label, named.interval_s) == ("Home Ollama", MAX_INTERVAL_S)


class CountingThrottle:
    def __init__(self) -> None:
        self.calls = 0

    async def wait(self) -> float:
        self.calls += 1
        return 0.0


def test_the_factories_attach_the_throttle() -> None:
    plain = get_llm(CredentialProvider.OPENROUTER, config())
    waiting = get_llm(
        CredentialProvider.OPENROUTER,
        config(min_interval_s=2.0, throttle_key="throttle:u:openrouter"),
    )
    voice = get_tts(
        CredentialProvider.OPENROUTER,
        config(min_interval_s=2.0, throttle_key="throttle:u:openrouter"),
    )

    assert plain.throttle is None
    assert isinstance(waiting.throttle, RequestThrottle)
    assert isinstance(voice.throttle, RequestThrottle)


@respx.mock
async def test_every_chat_request_waits_first_including_a_retry_after_a_429() -> None:
    route = respx.post(OPENROUTER_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "0"}),
            httpx.Response(200, json=completion("hi")),
        ]
    )
    llm = get_llm(
        CredentialProvider.OPENROUTER,
        config(),
        retry=RetryPolicy(max_attempts=3, initial_wait_s=0.0, max_wait_s=0.0),
    )
    counter = CountingThrottle()
    llm.throttle = counter

    await llm.complete([Message("user", "x")], model="vendor/model")
    await llm.aclose()

    assert route.call_count == 2 and counter.calls == 2


@respx.mock
async def test_listing_models_is_not_throttled() -> None:
    respx.get("https://openrouter.ai/api/v1/models").respond(200, json={"data": []})
    llm = get_llm(CredentialProvider.OPENROUTER, config())
    counter = CountingThrottle()
    llm.throttle = counter

    await llm.list_models()
    await llm.aclose()

    assert counter.calls == 0


@respx.mock
async def test_every_speech_request_waits_first_but_listing_voices_does_not(tmp_path) -> None:  # type: ignore[no-untyped-def]
    route = respx.post("https://openrouter.ai/api/v1/audio/speech").mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "0"}),
            httpx.Response(200, content=pcm_bytes()),
        ]
    )
    tts = get_tts(CredentialProvider.OPENROUTER, config(), retry=FAST_RETRY)
    counter = CountingThrottle()
    tts.throttle = counter

    await tts.synthesize(
        "Hello there.", voice_id="alloy", output_dir=tmp_path, params={"model": "m/x"}
    )
    await tts.list_voices()
    await tts.aclose()

    assert route.call_count == 2 and counter.calls == 2


# --- the setting, from the database -----------------------------------------------------------


async def test_the_resolver_adds_the_wait_of_the_provider_or_connection(
    db_session: AsyncSession, admin_user: User
) -> None:
    resolver = CredentialResolver(
        db_session, make_settings(openrouter_api_key=SecretStr("sk-or-test-12345678"))
    )
    plain = await resolver.get(admin_user.id, CredentialProvider.OPENROUTER)
    await save_request_interval(db_session, admin_user.id, "openrouter", 5.0)
    waiting = await resolver.get(admin_user.id, CredentialProvider.OPENROUTER)
    connection = await make_connection(db_session, admin_user, "Slow box")
    connection.min_interval_s = 2.5
    await db_session.flush()
    ref = ProviderRef(connection_id=connection.id)
    conn_config = await resolver.get_ref(admin_user.id, ref)

    assert plain.min_interval_s == 0
    assert (waiting.min_interval_s, waiting.throttle_key) == (
        5.0,
        f"throttle:{admin_user.id}:openrouter",
    )
    assert (conn_config.min_interval_s, conn_config.throttle_key) == (
        2.5,
        f"throttle:{admin_user.id}:conn:{connection.id}",
    )


async def test_each_user_has_their_own_wait_and_zero_removes_it(
    db_session: AsyncSession, admin_user: User
) -> None:
    other = await make_user(db_session, "other@example.com")
    await save_request_interval(db_session, admin_user.id, "openrouter", 5.0)
    await save_request_interval(db_session, admin_user.id, "openai", 1.0)

    assert await request_interval(db_session, other.id, "openrouter") == 0
    await save_request_interval(db_session, admin_user.id, "openrouter", 0)
    assert await request_intervals(db_session, admin_user.id) == {"openai": 1.0}


# --- in the run's log -------------------------------------------------------------------------


async def test_a_wait_noted_by_a_provider_becomes_a_line_of_the_run_log(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    run = await create_run(db_session, admin_user.id, show.id)

    async def waiting(ctx: RunContext) -> None:
        # What a throttle does from inside a provider call, with no access to the database.
        record_notice("Waiting 4.8 s for the OpenRouter rate limit")
        await ctx.progress(0.5)
        record_notice("Waiting 5.0 s for the OpenRouter rate limit")
        await ctx.log("script written")

    async def finish(ctx: RunContext) -> None:
        ctx.run.status = RunStatus.SUCCEEDED
        ctx.run.progress = 100
        ctx.run.finished_at = datetime.now(UTC)
        await ctx.session.commit()

    stages = [Stage("script", waiting, 0, 50), Stage("finalize", finish, 50, 100)]
    for s in stages:
        await run_stage(db_session, make_settings(), run.id, s.name, stages=stages)

    rows = await db_session.scalars(
        select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.ts, RunEvent.id)
    )
    messages = [
        e.message for e in rows if "rate limit" in e.message or e.message == "script written"
    ]
    assert messages == [
        "Waiting 4.8 s for the OpenRouter rate limit",
        "Waiting 5.0 s for the OpenRouter rate limit",
        "script written",
    ]
