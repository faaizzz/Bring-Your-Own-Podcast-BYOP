import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Run, UsageEvent, User
from byop.models.enums import CostSource, RunStatus, RunTrigger, UsageKind
from byop.providers.common import UsageRecord, current_usage_sink, record_usage
from byop.services.usage import UsageCollector, capture_usage, refresh_run_totals
from tests.models.factories import make_show


def usage(kind: str = "llm", **values: object) -> UsageRecord:
    base: dict[str, object] = {
        "kind": kind,
        "provider": "openrouter" if kind == "llm" else "kokoro",
        "model": "m/x",
        "stage": "script" if kind == "llm" else "tts",
        "run_id": None,
        "show_id": None,
        "latency_ms": 12,
    }
    return UsageRecord(**{**base, **values})  # type: ignore[arg-type]


async def events(session: AsyncSession) -> list[UsageEvent]:
    return list(await session.scalars(select(UsageEvent).order_by(UsageEvent.created_at)))


async def test_flush_stores_one_priced_event_per_call(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    run = Run(user_id=admin_user.id, show_id=show.id, trigger=RunTrigger.MANUAL)
    db_session.add(run)
    await db_session.flush()
    collector = UsageCollector()
    collector.record(
        usage(
            input_tokens=1200,
            output_tokens=300,
            cost_usd=Decimal("0.0042"),
            run_id=run.id,
            show_id=show.id,
        )
    )
    collector.record(usage("tts", characters=500, run_id=run.id, show_id=show.id))

    assert collector.pending == 2
    assert await collector.flush(db_session, admin_user.id) == 2
    assert collector.pending == 0

    llm_event, tts_event = await events(db_session)
    assert (llm_event.kind, llm_event.provider, llm_event.model, llm_event.stage) == (
        UsageKind.LLM,
        "openrouter",
        "m/x",
        "script",
    )
    assert (llm_event.input_tokens, llm_event.output_tokens) == (1200, 300)
    assert (llm_event.cost_usd, llm_event.cost_source) == (Decimal("0.004200"), CostSource.PROVIDER)
    assert (llm_event.run_id, llm_event.show_id, llm_event.latency_ms) == (run.id, show.id, 12)
    assert tts_event.kind is UsageKind.TTS and tts_event.characters == 500
    assert tts_event.cost_source is CostSource.PRICE_TABLE and tts_event.cost_usd == 0  # kokoro
    assert await collector.flush(db_session, admin_user.id) == 0  # nothing left


async def test_unpriced_calls_are_stored_as_unknown(
    db_session: AsyncSession, admin_user: User
) -> None:
    collector = UsageCollector()
    collector.record(usage(model="nobody/knows-this", input_tokens=5, output_tokens=5))

    await collector.flush(db_session, admin_user.id)

    (event,) = await events(db_session)
    assert event.cost_source is CostSource.UNKNOWN and event.cost_usd == 0


async def test_capture_collects_provider_calls_and_writes_them_afterwards(
    db_session: AsyncSession, admin_user: User
) -> None:
    assert current_usage_sink() is None
    async with capture_usage(db_session, admin_user.id) as collector:
        record_usage(usage(cost_usd=Decimal("0.01")))
        assert current_usage_sink() is collector
        assert await events(db_session) == []  # written when the block ends

    assert current_usage_sink() is None
    assert len(await events(db_session)) == 1


async def test_capture_writes_what_was_used_even_when_the_work_fails(
    db_session: AsyncSession, admin_user: User
) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        async with capture_usage(db_session, admin_user.id):
            record_usage(usage(cost_usd=Decimal("0.01")))
            raise RuntimeError("boom")

    assert len(await events(db_session)) == 1


async def test_a_capture_inside_another_joins_it(
    db_session: AsyncSession, admin_user: User
) -> None:
    async with capture_usage(db_session, admin_user.id) as outer:
        async with capture_usage(db_session, admin_user.id) as inner:
            assert inner is outer
            record_usage(usage(cost_usd=Decimal("0.01")))
        assert await events(db_session) == []  # still the outer block's to write
    assert len(await events(db_session)) == 1


def test_without_a_collector_usage_is_simply_dropped() -> None:
    record_usage(usage())  # must not raise


async def test_a_failing_write_never_hides_the_outcome_of_the_work(
    db_session: AsyncSession, admin_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(self: UsageCollector, session: AsyncSession, user_id: uuid.UUID) -> int:
        raise ConnectionError("database went away")

    monkeypatch.setattr(UsageCollector, "flush", broken)

    async with capture_usage(db_session, admin_user.id):
        record_usage(usage())  # no exception escapes the block


async def test_run_totals_are_the_sums_of_the_runs_events(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    run = Run(user_id=admin_user.id, show_id=show.id, trigger=RunTrigger.MANUAL)
    other = Run(
        user_id=admin_user.id,
        show_id=show.id,
        trigger=RunTrigger.SCHEDULE,
        status=RunStatus.SUCCEEDED,
    )
    db_session.add_all([run, other])
    await db_session.flush()
    collector = UsageCollector()
    for cost in ("0.010000", "0.002500", "0.000007"):
        collector.record(usage(cost_usd=Decimal(cost), run_id=run.id))
    collector.record(usage("tts", characters=1_000_000, provider="openai", run_id=run.id))
    collector.record(usage(cost_usd=Decimal("9"), run_id=other.id))
    await collector.flush(db_session, admin_user.id)

    await refresh_run_totals(db_session, run)

    rows = await events(db_session)
    llm_sum = sum(
        (e.cost_usd for e in rows if e.run_id == run.id and e.kind is UsageKind.LLM), Decimal(0)
    )
    tts_sum = sum(
        (e.cost_usd for e in rows if e.run_id == run.id and e.kind is UsageKind.TTS), Decimal(0)
    )
    assert run.llm_cost_usd == llm_sum == Decimal("0.012507")
    assert run.tts_cost_usd == tts_sum == Decimal("15.000000")  # openai's table price
    assert run.cost_usd == llm_sum + tts_sum
    await refresh_run_totals(db_session, other)
    assert other.cost_usd == Decimal("9.000000")


async def test_a_run_without_events_costs_nothing(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    run = Run(user_id=admin_user.id, show_id=show.id, trigger=RunTrigger.MANUAL)
    db_session.add(run)
    await db_session.flush()

    await refresh_run_totals(db_session, run)

    assert run.cost_usd == run.llm_cost_usd == run.tts_cost_usd == Decimal(0)
