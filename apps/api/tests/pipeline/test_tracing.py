import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx
from pydantic import SecretStr
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings
from byop.models import Run, Show, User
from byop.models.enums import RunStatus
from byop.pipeline.context import RunContext
from byop.pipeline.errors import StageFailed, TransientStageError
from byop.pipeline.orchestrator import Stage, StageResult, run_stage
from byop.providers.common import UsageRecord, record_usage
from byop.services import runs as run_service
from byop.services.langfuse import span_id
from tests.helpers import make_settings
from tests.models.factories import make_show

HOST = "https://langfuse.test"
INGEST = f"{HOST}/api/public/ingestion"


def traced() -> Settings:
    return make_settings(
        langfuse_public_key=SecretStr("pk-lf-test"),
        langfuse_secret_key=SecretStr("sk-lf-test"),
        langfuse_host=HOST,
    )


def events_of(route: respx.Route) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []
    for call in route.calls:
        sent += json.loads(call.request.content)["batch"]
    return sent


def of_type(events: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [e["body"] for e in events if e["type"] == kind]


def llm_call(ctx: RunContext, **values: Any) -> None:
    base: dict[str, Any] = {
        "kind": "llm",
        "provider": "openrouter",
        "model": "vendor/model-1",
        "stage": ctx.stage,
        "run_id": ctx.run.id,
        "show_id": ctx.show.id,
        "latency_ms": 800,
        "input_tokens": 120,
        "output_tokens": 30,
        "cost_usd": Decimal("0.0007"),
        "started_at": datetime.now(UTC),
        "prompt": json.dumps([{"role": "user", "content": "Write the script"}]),
        "completion": "Alex: Hello!",
    }
    record_usage(UsageRecord(**{**base, **values}))


def voice_call(ctx: RunContext) -> None:
    record_usage(
        UsageRecord(
            kind="tts",
            provider="openai",
            model=None,
            stage=ctx.stage,
            run_id=ctx.run.id,
            show_id=ctx.show.id,
            latency_ms=1200,
            characters=1000,
            tags={"speaker": "Alex", "voice": "alloy"},
        )
    )


async def last(ctx: RunContext) -> None:
    ctx.run.status = RunStatus.SUCCEEDED
    ctx.run.progress = 100
    ctx.run.finished_at = datetime.now(UTC)
    await ctx.session.commit()


async def new_run(session: AsyncSession, user: User) -> tuple[Run, Show]:
    show = await make_show(session, user)
    show.title = "Daily AI"
    return await run_service.create_run(session, user.id, show.id), show


async def test_a_run_becomes_one_trace_with_a_span_per_stage_and_a_generation_per_call(
    db_session: AsyncSession, admin_user: User
) -> None:
    run, show = await new_run(db_session, admin_user)

    async def writing(ctx: RunContext) -> None:
        llm_call(ctx)
        llm_call(ctx, cost_usd=None, input_tokens=1_000_000, output_tokens=0, model="gpt-4.1")

    async def voicing(ctx: RunContext) -> None:
        voice_call(ctx)

    stages = [
        Stage("script", writing, 0, 40),
        Stage("tts", voicing, 40, 90),
        Stage("done", last, 90, 100),
    ]
    with respx.mock:
        route = respx.post(INGEST).respond(207, json={"successes": [], "errors": []})
        for s in stages:
            assert (
                await run_stage(db_session, traced(), run.id, s.name, stages=stages)
                is StageResult.DONE
            )

    events = events_of(route)
    await db_session.refresh(run)
    trace_id = run.trace_id
    assert trace_id and len(trace_id) == 32

    # One trace for the whole run, named after the show and grouped by show.
    traces = [b for b in of_type(events, "trace-create") if "name" in b]
    assert {b["id"] for b in of_type(events, "trace-create")} == {trace_id}
    assert traces[0]["name"] == "Daily AI" and traces[0]["sessionId"] == str(show.id)
    assert traces[0]["tags"] == ["manual", "news_briefing"]
    assert traces[0]["metadata"]["run_id"] == str(run.id)

    # A span per stage, opened and closed, all inside the trace.
    created = {
        b["name"]: b
        for b in of_type(events, "span-create")
        if b.get("name") in {"script", "tts", "done"}
    }
    assert set(created) == {"script", "tts", "done"}
    assert created["script"]["id"] == span_id(run.id, "script")
    closed = {b["id"] for b in of_type(events, "span-update")}
    assert closed == {span_id(run.id, s.name) for s in stages}
    assert all(
        b["traceId"] == trace_id
        for b in of_type(events, "span-create") + of_type(events, "span-update")
    )

    # A generation per language-model call, under its stage's span, with tokens and cost.
    first, second = of_type(events, "generation-create")
    assert first["parentObservationId"] == span_id(run.id, "script")
    assert (first["model"], first["output"]) == ("vendor/model-1", "Alex: Hello!")
    assert json.loads(first["input"]) == [{"role": "user", "content": "Write the script"}]
    assert first["usageDetails"] == {"input": 120, "output": 30, "total": 150}
    assert first["costDetails"] == {"total": 0.0007}  # the provider's figure
    assert second["costDetails"] == {"total": 2.0}  # priced from the table: 1M tokens of gpt-4.1
    assert first["traceId"] == trace_id

    # A span per voice call: characters, cost and who spoke.
    voice = next(b for b in of_type(events, "span-create") if b.get("name") == "tts openai")
    assert voice["parentObservationId"] == span_id(run.id, "tts")
    assert voice["metadata"]["characters"] == 1000
    assert Decimal(voice["metadata"]["cost_usd"]) == Decimal("0.015")
    assert (voice["metadata"]["speaker"], voice["metadata"]["voice"]) == ("Alex", "alloy")

    # The run's end is recorded on the trace.
    final = [b for b in of_type(events, "trace-create") if "output" in b]
    assert final and final[-1]["metadata"] == {"status": "ok"}


async def test_requests_use_the_keys_and_host_from_the_settings(
    db_session: AsyncSession, admin_user: User
) -> None:
    run, _ = await new_run(db_session, admin_user)
    stages = [Stage("done", last, 0, 100)]
    with respx.mock:
        route = respx.post(INGEST).respond(207, json={})
        await run_stage(db_session, traced(), run.id, "done", stages=stages)

    request = route.calls[0].request
    assert request.headers["authorization"].startswith("Basic ")
    import base64

    assert base64.b64decode(request.headers["authorization"][6:]) == b"pk-lf-test:sk-lf-test"


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("no route to host"),
        httpx.ReadTimeout("slow"),
        httpx.Response(500, text="boom"),
        httpx.Response(401, json={"message": "bad keys"}),
    ],
    ids=["unreachable", "timeout", "server error", "wrong keys"],
)
async def test_a_run_succeeds_whatever_langfuse_does(
    db_session: AsyncSession, admin_user: User, failure: Exception | httpx.Response
) -> None:
    run, _ = await new_run(db_session, admin_user)

    async def work(ctx: RunContext) -> None:
        llm_call(ctx)
        await ctx.log("still working")

    stages = [Stage("work", work, 0, 50), Stage("done", last, 50, 100)]
    with respx.mock:
        route = respx.post(INGEST)
        route.side_effect = [failure] * 10 if isinstance(failure, Exception) else None
        if isinstance(failure, httpx.Response):
            route.mock(return_value=failure)
        results = [
            await run_stage(db_session, traced(), run.id, s.name, stages=stages) for s in stages
        ]

    assert results == [StageResult.DONE, StageResult.DONE]
    assert route.called  # Langfuse really was tried
    await db_session.refresh(run)
    assert run.status is RunStatus.SUCCEEDED and run.error is None


async def test_without_langfuse_nothing_is_sent_and_no_trace_id_is_made(
    db_session: AsyncSession, admin_user: User
) -> None:
    run, _ = await new_run(db_session, admin_user)

    async def work(ctx: RunContext) -> None:
        llm_call(ctx)

    stages = [Stage("work", work, 0, 50), Stage("done", last, 50, 100)]
    with respx.mock(assert_all_called=False) as router:
        route = router.post(INGEST).respond(207, json={})
        for s in stages:
            await run_stage(db_session, make_settings(), run.id, s.name, stages=stages)

    assert route.call_count == 0
    await db_session.refresh(run)
    assert run.trace_id is None and run.status is RunStatus.SUCCEEDED


async def test_a_failed_stage_marks_its_span_and_the_trace(
    db_session: AsyncSession, admin_user: User
) -> None:
    run, _ = await new_run(db_session, admin_user)

    async def breaks(ctx: RunContext) -> None:
        llm_call(ctx)
        raise StageFailed("the model said nonsense")

    with respx.mock:
        route = respx.post(INGEST).respond(207, json={})
        result = await run_stage(
            db_session, traced(), run.id, "script", stages=[Stage("script", breaks, 0, 100)]
        )

    assert result is StageResult.FAILED
    events = events_of(route)
    (closing,) = of_type(events, "span-update")
    assert closing["level"] == "ERROR" and closing["statusMessage"] == "the model said nonsense"
    final = [b for b in of_type(events, "trace-create") if "output" in b]
    assert final[-1]["output"] == "the model said nonsense" and final[-1]["metadata"] == {
        "status": "failed"
    }
    assert len(of_type(events, "generation-create")) == 1  # the call made before the failure


async def test_a_cancelled_run_is_traced_as_a_warning(
    db_session: AsyncSession, admin_user: User
) -> None:
    run, _ = await new_run(db_session, admin_user)

    async def stops(ctx: RunContext) -> None:
        await ctx.session.execute(
            update(Run).where(Run.id == ctx.run.id).values(cancel_requested=True)
        )
        await ctx.session.commit()
        await ctx.checkpoint()

    with respx.mock:
        route = respx.post(INGEST).respond(207, json={})
        result = await run_stage(
            db_session, traced(), run.id, "script", stages=[Stage("script", stops, 0, 100)]
        )

    assert result is StageResult.CANCELLED
    (closing,) = of_type(events_of(route), "span-update")
    assert closing["level"] == "WARNING"


async def test_a_retried_stage_reuses_its_span_instead_of_adding_one(
    db_session: AsyncSession, admin_user: User
) -> None:
    run, _ = await new_run(db_session, admin_user)
    attempts = {"n": 0}

    async def flaky(ctx: RunContext) -> None:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise TransientStageError("provider hiccup")

    stages = [Stage("tts", flaky, 0, 100)]
    with respx.mock:
        route = respx.post(INGEST).respond(207, json={})
        with pytest.raises(TransientStageError):
            await run_stage(db_session, traced(), run.id, "tts", stages=stages)
        await run_stage(db_session, traced(), run.id, "tts", stages=stages)

    events = events_of(route)
    creates = [b for b in of_type(events, "span-create") if b.get("name") == "tts"]
    assert len(creates) == 2 and len({b["id"] for b in creates}) == 1
    first_close = of_type(events, "span-update")[0]
    assert first_close["level"] == "WARNING"  # the failed attempt
    # The trace is not finished by a retry.
    assert not [
        b
        for b in of_type(events, "trace-create")
        if "output" in b and b["metadata"] == {"status": "failed"}
    ]


async def test_long_prompts_are_cut(db_session: AsyncSession, admin_user: User) -> None:
    run, _ = await new_run(db_session, admin_user)

    async def work(ctx: RunContext) -> None:
        llm_call(ctx, prompt="x" * 50_000, completion="y" * 30_000)

    with respx.mock:
        route = respx.post(INGEST).respond(207, json={})
        await run_stage(db_session, traced(), run.id, "work", stages=[Stage("work", work, 0, 100)])

    (generation,) = of_type(events_of(route), "generation-create")
    assert len(generation["input"]) < 20_100 and "more characters" in generation["input"]
    assert len(generation["output"]) < 20_100


async def test_every_event_has_an_id_type_and_timestamp(
    db_session: AsyncSession, admin_user: User
) -> None:
    run, _ = await new_run(db_session, admin_user)
    with respx.mock:
        route = respx.post(INGEST).respond(207, json={})
        await run_stage(db_session, traced(), run.id, "done", stages=[Stage("done", last, 0, 100)])

    for event in events_of(route):
        assert (
            uuid.UUID(event["id"]) and event["type"] and datetime.fromisoformat(event["timestamp"])
        )
