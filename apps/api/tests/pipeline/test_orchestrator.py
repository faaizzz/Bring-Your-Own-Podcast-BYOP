import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import httpx
import pytest
import respx
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings
from byop.models import Episode, Item, Run, RunEvent, Show, Source, Speaker, User
from byop.models.enums import EpisodeStatus, EventLevel, RunStatus, RunTrigger, SourceKind
from byop.pipeline.context import RunContext
from byop.pipeline.errors import StageFailed, TransientStageError
from byop.pipeline.orchestrator import (
    STAGES,
    Stage,
    StageResult,
    reap_stuck_runs,
    run_stage,
)
from byop.pipeline.stages import finalize
from byop.services import runs as run_service
from byop.services.ranking import reserve_items
from tests.helpers import make_settings
from tests.models.factories import make_show
from tests.providers.llm.helpers import OPENROUTER_URL, completion
from tests.providers.tts.helpers import pcm_bytes

pytestmark = pytest.mark.usefixtures("fake_dns")


def stage(name: str, run, start: int, end: int) -> Stage:  # type: ignore[no-untyped-def]
    return Stage(name, run, start, end)


async def ok(ctx: RunContext) -> None:
    await ctx.log(f"{ctx.stage} did its work", step=1)
    await ctx.progress(0.5)
    await ctx.progress(1.0)


async def last(ctx: RunContext) -> None:
    """A final stage that ends the run, as the real finalize does."""
    await ctx.checkpoint()
    ctx.run.status = RunStatus.SUCCEEDED
    ctx.run.progress = 100
    ctx.run.finished_at = datetime.now(UTC)
    await ctx.session.commit()


def chain_of(*middle: Stage) -> list[Stage]:
    return [stage("first", ok, 0, 30), *middle, stage("last", last, 90, 100)]


async def start(session: AsyncSession, user: User, show: Show) -> Run:
    return await run_service.create_run(session, user.id, show.id)


async def execute(
    session: AsyncSession, settings: Settings, run: Run, stages: list[Stage]
) -> list[StageResult]:
    """What the Celery chain does: each stage in turn."""
    return [await run_stage(session, settings, run.id, s.name, stages=stages) for s in stages]


async def reload(session: AsyncSession, run: Run) -> Run:
    await session.refresh(run)
    return run


async def events(session: AsyncSession, run: Run) -> list[RunEvent]:
    rows = await session.scalars(
        select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.ts, RunEvent.id)
    )
    return list(rows)


# --- success ----------------------------------------------------------------------------------


async def test_a_run_goes_through_every_stage_and_ends_succeeded(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    run = await start(db_session, admin_user, show)
    assert run.status is RunStatus.QUEUED
    stages = chain_of(stage("middle", ok, 30, 90))

    results = await execute(db_session, make_settings(), run, stages)

    assert results == [StageResult.DONE] * 3
    run = await reload(db_session, run)
    assert run.status is RunStatus.SUCCEEDED and run.progress == 100
    assert run.started_at is not None and run.finished_at is not None
    assert run.stage == "last" and run.error is None
    messages = [e.message for e in await events(db_session, run)]
    assert messages[0] == "Run queued"
    assert "Started first" in messages and "first did its work" in messages
    assert messages.index("Started middle") > messages.index("Finished first")
    assert "Finished middle" in messages


async def test_progress_follows_the_stage_ranges_and_never_goes_backwards(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    run = await start(db_session, admin_user, show)
    seen: list[int] = []

    async def watch(ctx: RunContext) -> None:
        seen.append(ctx.run.progress)
        await ctx.progress(0.25)
        seen.append(ctx.run.progress)
        await ctx.progress(2.0)  # clamped to the end of the stage's range
        seen.append(ctx.run.progress)

    await execute(db_session, make_settings(), run, chain_of(stage("watch", watch, 40, 80)))

    assert seen == [40, 50, 80]


async def test_the_real_pipeline_runs_end_to_end_with_a_stub_mix(
    db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    show = await make_show(db_session, admin_user)
    show.target_minutes = 1
    voice = {"tts_provider": "kokoro", "user_id": admin_user.id, "show_id": show.id}
    db_session.add_all(
        [
            Source(
                user_id=admin_user.id,
                show_id=show.id,
                kind=SourceKind.RSS,
                value="https://f.example.com/rss",
            ),
            Speaker(position=0, name="Alex", voice_id="af_bella", **voice),
            Speaker(position=1, name="Sam", voice_id="am_michael", **voice),
        ]
    )
    await db_session.flush()
    feed = (
        '<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
        "<item><title>Researchers map the deep ocean floor with new sonar</title>"
        "<link>https://f.example.com/1</link><description>Scientists explained how the new sonar "
        "works and why the map matters for the community.</description></item>"
        "<item><title>City council approves a plan for new cycling lanes</title>"
        "<link>https://f.example.com/2</link><description>The council voted to build protected "
        "lanes along the main roads over the coming year.</description></item>"
        "</channel></rss>"
    )
    words = " ".join(["word"] * 45)  # 3 segments of ~47 words: inside 120-180 for 1 minute
    script = {
        "title": "Oceans and bikes",
        "description": "Sonar maps and cycling lanes.",
        "segments": [
            {"speaker": "Alex", "text": f"Welcome. {words}", "kind": "intro", "item_ids": []},
            {"speaker": "Sam", "text": f"Sonar story. {words}", "kind": "story", "item_ids": [1]},
            {"speaker": "Alex", "text": f"Bikes story. {words}", "kind": "story", "item_ids": [2]},
        ],
    }
    ranking = {"selections": [{"item": 1, "score": 9, "reason": "Big."}, {"item": 2, "score": 7}]}
    run = await start(db_session, admin_user, show)
    cfg = make_settings(
        openrouter_api_key=SecretStr("sk-or-test-key-123456"),
        default_llm_provider="openrouter",
        default_llm_model="vendor/model",
        kokoro_base_url="http://kokoro:8880/v1",
        media_root=str(tmp_path),
    )

    with respx.mock:
        respx.post("http://kokoro:8880/v1/audio/speech").respond(200, content=pcm_bytes())
        respx.get("https://f.example.com/rss").respond(
            200, content=feed.encode(), headers={"content-type": "application/rss+xml"}
        )
        respx.post(OPENROUTER_URL).mock(
            side_effect=[
                httpx.Response(200, json=completion(json.dumps(ranking))),
                httpx.Response(200, json=completion(json.dumps(script))),
            ]
        )
        results = await execute(db_session, cfg, run, STAGES)

    assert results == [StageResult.DONE] * len(STAGES)
    run = await reload(db_session, run)
    assert run.status is RunStatus.SUCCEEDED and run.progress == 100
    assert run.selection is not None and len(run.selection["stories"]) == 2  # type: ignore[arg-type]
    log = await events(db_session, run)
    assert any(e.message.startswith("Collected 2 new items") for e in log)
    chose = next(e for e in log if e.message.startswith("Chose "))
    assert chose.data is not None and len(cast(list[object], chose.data["stories"])) == 2
    assert any(e.message.startswith("Wrote “Oceans and bikes”") for e in log)
    assert any(e.message.startswith("Voiced 3 chunks") for e in log)
    assert any(e.message.startswith("Episode audio ready") for e in log)
    assert not (tmp_path / "work").exists() or not any((tmp_path / "work").iterdir())
    episode = await db_session.scalar(select(Episode).where(Episode.run_id == run.id))
    assert episode is not None and episode.title == "Oceans and bikes"
    assert episode.status is EpisodeStatus.DRAFT and episode.script is not None
    assert episode.audio_key is not None and (tmp_path / episode.audio_key).is_file()
    assert episode.duration_s and episode.duration_s > 0 and episode.size_bytes
    # The stories now belong to the draft episode, and nothing is left reserved.
    items = list(await db_session.scalars(select(Item).where(Item.show_id == show.id)))
    assert {i.used_in_episode_id for i in items} == {episode.id}
    assert {i.reserved_run_id for i in items} == {None}


# --- failure ---------------------------------------------------------------------------------


async def test_a_failed_stage_fails_the_run_and_the_rest_are_skipped(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    run = await start(db_session, admin_user, show)

    async def boom(ctx: RunContext) -> None:
        raise StageFailed("There is nothing to talk about")

    stages = chain_of(stage("boom", boom, 30, 60), stage("never", ok, 60, 90))

    results = await execute(db_session, make_settings(), run, stages)

    assert results == [
        StageResult.DONE,
        StageResult.FAILED,
        StageResult.SKIPPED,
        StageResult.SKIPPED,
    ]
    await db_session.refresh(run)
    assert run.status is RunStatus.FAILED and run.error == "There is nothing to talk about"
    assert run.finished_at is not None and run.stage == "boom"
    failure = [e for e in await events(db_session, run) if e.level is EventLevel.ERROR]
    assert [(e.stage, e.message) for e in failure] == [("boom", "There is nothing to talk about")]
    assert "Started never" not in [e.message for e in await events(db_session, run)]


async def test_an_unexpected_exception_fails_the_run_with_its_type(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    run = await start(db_session, admin_user, show)

    async def crash(ctx: RunContext) -> None:
        raise ValueError("disk on fire")

    results = await execute(
        db_session, make_settings(), run, chain_of(stage("crash", crash, 30, 60))
    )

    assert results[1] is StageResult.FAILED
    await db_session.refresh(run)
    assert run.status is RunStatus.FAILED
    assert run.error == "Unexpected error in crash: ValueError: disk on fire"


async def test_a_failing_run_gives_its_reserved_stories_back(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    item = Item(
        user_id=admin_user.id, show_id=show.id, canonical_url="https://e.com/1",
        content_hash="a" * 64, title="Story",
    )  # fmt: skip
    db_session.add(item)
    run = await start(db_session, admin_user, show)
    await db_session.flush()
    await reserve_items(db_session, show, run.id, [item.id])

    async def boom(ctx: RunContext) -> None:
        raise StageFailed("later stage failed")

    await execute(db_session, make_settings(), run, chain_of(stage("boom", boom, 30, 60)))

    await db_session.refresh(item)
    assert item.reserved_run_id is None


async def test_a_transient_error_is_raised_for_retry_and_the_run_keeps_going(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    run = await start(db_session, admin_user, show)
    attempts = {"n": 0}

    async def flaky(ctx: RunContext) -> None:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise TransientStageError("provider said 503")
        await ctx.log("worked on the second try")

    stages = chain_of(stage("flaky", flaky, 30, 60))
    await run_stage(db_session, make_settings(), run.id, "first", stages=stages)

    with pytest.raises(TransientStageError):
        await run_stage(db_session, make_settings(), run.id, "flaky", stages=stages)
    await db_session.refresh(run)
    assert run.status is RunStatus.RUNNING  # not failed: the task will retry
    assert any(
        e.level is EventLevel.WARNING and "will retry: provider said 503" in e.message
        for e in await events(db_session, run)
    )

    assert (
        await run_stage(db_session, make_settings(), run.id, "flaky", stages=stages)
        is StageResult.DONE
    )
    assert (
        await run_stage(db_session, make_settings(), run.id, "last", stages=stages)
        is StageResult.DONE
    )
    assert (await reload(db_session, run)).status is RunStatus.SUCCEEDED


# --- cancel ------------------------------------------------------------------------------------


async def test_cancelling_a_queued_run_ends_it_at_once_and_its_stages_do_nothing(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    run = await start(db_session, admin_user, show)

    cancelled = await run_service.request_cancel(db_session, admin_user.id, run.id)

    assert cancelled.status is RunStatus.CANCELLED and cancelled.finished_at is not None
    results = await execute(db_session, make_settings(), run, chain_of())
    assert results == [StageResult.SKIPPED, StageResult.SKIPPED]
    assert "Run cancelled before it started" in [e.message for e in await events(db_session, run)]


async def test_a_running_run_stops_at_its_next_checkpoint_and_releases_its_stories(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    item = Item(
        user_id=admin_user.id, show_id=show.id, canonical_url="https://e.com/1",
        content_hash="b" * 64, title="Story",
    )  # fmt: skip
    db_session.add(item)
    run = await start(db_session, admin_user, show)
    await db_session.flush()
    reached: list[str] = []

    async def long_job(ctx: RunContext) -> None:
        await reserve_items(ctx.session, ctx.show, ctx.run.id, [item.id])
        reached.append("step 1")
        # the user presses cancel while the stage is working
        await ctx.session.execute(
            update(Run).where(Run.id == ctx.run.id).values(cancel_requested=True)
        )
        await ctx.session.commit()
        await ctx.checkpoint()
        reached.append("step 2")  # never reached

    stages = chain_of(stage("long", long_job, 30, 60), stage("after", ok, 60, 90))

    results = await execute(db_session, make_settings(), run, stages)

    assert results == [
        StageResult.DONE,
        StageResult.CANCELLED,
        StageResult.SKIPPED,
        StageResult.SKIPPED,
    ]
    assert reached == ["step 1"]
    await db_session.refresh(run)
    assert run.status is RunStatus.CANCELLED and run.finished_at is not None
    await db_session.refresh(item)
    assert item.reserved_run_id is None
    assert "Run cancelled" in [e.message for e in await events(db_session, run)]


async def test_a_cancel_requested_between_stages_stops_the_next_one_before_it_starts(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    run = await start(db_session, admin_user, show)
    stages = chain_of(stage("never", ok, 30, 60))
    await run_stage(db_session, make_settings(), run.id, "first", stages=stages)
    await run_service.request_cancel(db_session, admin_user.id, run.id)  # running: flag only
    await db_session.refresh(run)
    assert run.status is RunStatus.RUNNING and run.cancel_requested

    result = await run_stage(db_session, make_settings(), run.id, "never", stages=stages)

    assert result is StageResult.CANCELLED
    assert (await reload(db_session, run)).status is RunStatus.CANCELLED
    assert "Started never" not in [e.message for e in await events(db_session, run)]


async def test_a_finished_run_cannot_be_cancelled(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    run = await start(db_session, admin_user, show)
    await execute(db_session, make_settings(), run, chain_of())

    with pytest.raises(run_service.RunConflict, match="already ended"):
        await run_service.request_cancel(db_session, admin_user.id, run.id)


# --- the reaper ----------------------------------------------------------------------------------


async def age(session: AsyncSession, run: Run, minutes: int) -> None:
    await session.execute(
        update(Run)
        .where(Run.id == run.id)
        .values(updated_at=datetime.now(UTC) - timedelta(minutes=minutes))
    )
    await session.refresh(run)


async def test_the_reaper_fails_runs_that_stopped_reporting_and_frees_their_stories(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    other = await make_show(db_session, admin_user, slug="other")
    third = await make_show(db_session, admin_user, slug="third")
    item = Item(
        user_id=admin_user.id, show_id=show.id, canonical_url="https://e.com/1",
        content_hash="c" * 64, title="Story",
    )  # fmt: skip
    db_session.add(item)
    stuck_running = await start(db_session, admin_user, show)
    stuck_queued = await start(db_session, admin_user, other)
    healthy = await start(db_session, admin_user, third)
    await db_session.flush()
    stuck_running.status = RunStatus.RUNNING
    stuck_running.stage = "tts"
    await db_session.flush()
    await reserve_items(db_session, show, stuck_running.id, [item.id])
    await age(db_session, stuck_running, 120)
    await age(db_session, stuck_queued, 90)
    await age(db_session, healthy, 5)

    reaped = await reap_stuck_runs(db_session, make_settings(run_timeout_minutes=60))

    assert set(reaped) == {stuck_running.id, stuck_queued.id}
    for run in (stuck_running, stuck_queued, healthy):
        await db_session.refresh(run)
    assert stuck_running.status is RunStatus.FAILED and stuck_queued.status is RunStatus.FAILED
    assert "Timed out: no progress for 60 minutes" in (stuck_running.error or "")
    assert stuck_running.finished_at is not None
    assert healthy.status is RunStatus.QUEUED
    await db_session.refresh(item)
    assert item.reserved_run_id is None
    log = await events(db_session, stuck_running)
    assert log[-1].level is EventLevel.ERROR and log[-1].stage == "tts"


async def test_the_reaper_leaves_finished_runs_alone_and_is_repeatable(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    done = await start(db_session, admin_user, show)
    await execute(db_session, make_settings(), done, chain_of())
    await age(db_session, done, 500)
    stuck = await start(db_session, admin_user, show)
    await age(db_session, stuck, 500)

    first = await reap_stuck_runs(db_session, make_settings())
    second = await reap_stuck_runs(db_session, make_settings())

    assert first == [stuck.id] and second == []
    await db_session.refresh(done)
    assert done.status is RunStatus.SUCCEEDED


async def test_a_run_that_keeps_reporting_is_not_reaped(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    run = await start(db_session, admin_user, show)
    await age(db_session, run, 50)

    async def busy(ctx: RunContext) -> None:
        await ctx.progress(0.5)  # a heartbeat

    await run_stage(
        db_session, make_settings(), run.id, "busy", stages=[stage("busy", busy, 0, 50)]
    )

    assert await reap_stuck_runs(db_session, make_settings(run_timeout_minutes=60)) == []
    await db_session.refresh(run)
    assert run.status is RunStatus.RUNNING


# --- one active run per show ------------------------------------------------------------------


async def test_only_one_run_per_show_can_be_active(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    other = await make_show(db_session, admin_user, slug="other")
    first = await start(db_session, admin_user, show)

    with pytest.raises(run_service.RunConflict, match="already in progress"):
        await start(db_session, admin_user, show)
    assert (await start(db_session, admin_user, other)).status is RunStatus.QUEUED  # another show

    await run_service.request_cancel(db_session, admin_user.id, first.id)
    assert (await start(db_session, admin_user, show)).status is RunStatus.QUEUED  # free again


async def test_the_database_itself_forbids_two_active_runs(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    db_session.add(Run(user_id=admin_user.id, show_id=show.id, trigger=RunTrigger.MANUAL))
    await db_session.flush()

    db_session.add(Run(user_id=admin_user.id, show_id=show.id, trigger=RunTrigger.SCHEDULE))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_a_run_waiting_for_review_does_not_block_the_next_one(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    waiting = await start(db_session, admin_user, show)
    waiting.status = RunStatus.AWAITING_REVIEW
    await db_session.flush()

    assert (await start(db_session, admin_user, show)).status is RunStatus.QUEUED


def test_the_real_pipeline_has_the_six_stages_in_order() -> None:
    assert [s.name for s in STAGES] == ["ingest", "rank", "script", "tts", "mix", "finalize"]
    assert STAGES[0].start == 0 and STAGES[-1].end == 100
    assert all(a.end == b.start for a, b in zip(STAGES, STAGES[1:], strict=False))
    assert STAGES[-1].run is finalize.run


async def test_unknown_runs_are_skipped_not_crashed(db_session: AsyncSession) -> None:
    assert (
        await run_stage(db_session, make_settings(), uuid.uuid4(), "ingest") is StageResult.SKIPPED
    )
