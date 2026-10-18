import asyncio
import json
import uuid
from collections.abc import AsyncIterator

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Run, User
from byop.models.enums import RunStatus
from byop.pipeline.orchestrator import STAGES, Stage, add_event, run_stage
from byop.redis_client import get_redis_client
from byop.services import runs as run_service
from byop.services.run_stream import announce, stream_run
from tests.helpers import make_settings
from tests.models.factories import make_show, make_user


def parse(message: str) -> tuple[str, dict[str, object]]:
    lines = message.strip().split("\n")
    assert lines[0].startswith("event: ") and lines[1].startswith("data: ")
    return lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))


async def new_run(session: AsyncSession, user: User) -> Run:
    show = await make_show(session, user)
    return await run_service.create_run(session, user.id, show.id)


async def change(session: AsyncSession, run: Run, **values: object) -> None:
    """Change the run the way another process would: behind the stream's back, in SQL."""
    await session.execute(update(Run).where(Run.id == run.id).values(**values))
    await session.commit()


async def opened(stream: AsyncIterator[str]) -> tuple[str, dict[str, object]]:
    """Skip the `retry:` preamble and return the first real message."""
    assert (await anext(stream)).startswith("retry:")
    return parse(await anext(stream))


async def test_the_first_message_is_a_snapshot_of_the_run_and_its_whole_log(
    db_session: AsyncSession, admin_user: User
) -> None:
    run = await new_run(db_session, admin_user)
    await add_event(db_session, run, "Collected 3 items", stage="ingest")
    await db_session.commit()

    event, data = await opened(
        stream_run(db_session, None, admin_user.id, run.id, poll_s=0.01, max_s=0.05)
    )

    assert event == "snapshot"
    assert data["run"]["status"] == "queued"  # type: ignore[index]
    assert [e["message"] for e in data["events"]] == ["Run queued", "Collected 3 items"]  # type: ignore[attr-defined]


async def test_changes_arrive_as_updates_with_only_the_new_lines_then_done(
    db_session: AsyncSession, admin_user: User
) -> None:
    run = await new_run(db_session, admin_user)
    stream = stream_run(db_session, None, admin_user.id, run.id, poll_s=0.01)
    await opened(stream)

    await add_event(db_session, run, "Started ingest", stage="ingest")
    await change(db_session, run, status=RunStatus.RUNNING, stage="ingest", progress=10)
    event, data = parse(await anext(stream))
    assert event == "update"
    assert data["run"]["progress"] == 10 and data["run"]["stage"] == "ingest"  # type: ignore[index]
    assert [e["message"] for e in data["events"]] == ["Started ingest"]  # type: ignore[attr-defined]

    await add_event(db_session, run, "Finished", stage="finalize")
    await change(db_session, run, status=RunStatus.SUCCEEDED, progress=100)
    event, data = parse(await anext(stream))
    assert event == "update" and [e["message"] for e in data["events"]] == ["Finished"]  # type: ignore[attr-defined]
    event, data = parse(await anext(stream))
    assert (event, data) == ("done", {"status": "succeeded"})
    assert [m async for m in stream] == []


async def test_a_finished_run_gets_a_snapshot_and_done(
    db_session: AsyncSession, admin_user: User
) -> None:
    run = await new_run(db_session, admin_user)
    run.status = RunStatus.FAILED
    run.error = "boom"
    await db_session.commit()

    messages = [m async for m in stream_run(db_session, None, admin_user.id, run.id)]

    assert [parse(m)[0] for m in messages[1:]] == ["snapshot", "done"]
    assert parse(messages[1])[1]["run"]["error"] == "boom"  # type: ignore[index]


async def test_a_reconnecting_client_is_brought_up_to_date_from_the_database(
    db_session: AsyncSession, admin_user: User
) -> None:
    run = await new_run(db_session, admin_user)
    first = stream_run(db_session, None, admin_user.id, run.id, poll_s=0.01)
    await opened(first)
    await add_event(db_session, run, "Voiced 3 of 9 lines", stage="tts")
    await change(db_session, run, status=RunStatus.RUNNING, stage="tts", progress=60)
    await first.aclose()  # the network dropped

    event, data = await opened(
        stream_run(db_session, None, admin_user.id, run.id, poll_s=0.01, max_s=0.05)
    )

    assert event == "snapshot"
    assert data["run"]["progress"] == 60  # type: ignore[index]
    assert [e["message"] for e in data["events"]][-1] == "Voiced 3 of 9 lines"  # type: ignore[attr-defined]


async def test_an_announcement_wakes_the_stream_long_before_the_poll_interval(
    db_session: AsyncSession, admin_user: User
) -> None:
    run = await new_run(db_session, admin_user)
    redis = get_redis_client()
    stream = stream_run(db_session, redis, admin_user.id, run.id, poll_s=60, heartbeat_s=60)
    await opened(stream)

    await change(db_session, run, progress=42)
    await announce(redis, run.id)

    event, data = parse(await asyncio.wait_for(anext(stream), timeout=5))
    assert event == "update" and data["run"]["progress"] == 42  # type: ignore[index]
    await stream.aclose()


async def test_an_idle_stream_sends_a_ping_to_keep_the_connection_open(
    db_session: AsyncSession, admin_user: User
) -> None:
    run = await new_run(db_session, admin_user)
    stream = stream_run(db_session, None, admin_user.id, run.id, poll_s=0.01, heartbeat_s=0.02)
    await opened(stream)

    assert await asyncio.wait_for(anext(stream), timeout=5) == ": ping\n\n"
    await stream.aclose()


async def test_the_stream_ends_after_its_time_limit_so_the_client_reconnects(
    db_session: AsyncSession, admin_user: User
) -> None:
    run = await new_run(db_session, admin_user)

    messages = [
        m
        async for m in stream_run(
            db_session, None, admin_user.id, run.id, poll_s=0.01, heartbeat_s=1, max_s=0.05
        )
    ]

    assert parse(messages[1])[0] == "snapshot"
    assert not any(m.startswith("event: done") for m in messages)


async def test_someone_elses_or_an_unknown_run_is_gone(
    db_session: AsyncSession, admin_user: User
) -> None:
    run = await new_run(db_session, admin_user)
    other = await make_user(db_session, "other@example.com")

    for user_id, run_id in ((other.id, run.id), (admin_user.id, uuid.uuid4())):
        event, _ = await opened(stream_run(db_session, None, user_id, run_id))
        assert event == "gone"


class FakeRedis:
    def __init__(self, *, broken: bool = False) -> None:
        self.published: list[tuple[str, str]] = []
        self.broken = broken

    async def publish(self, channel: str, message: str) -> int:
        if self.broken:
            raise ConnectionError("redis is down")
        self.published.append((channel, message))
        return 1


async def test_announcing_never_raises_even_when_redis_is_down() -> None:
    await announce(FakeRedis(broken=True), uuid.uuid4())  # type: ignore[arg-type]
    await announce(None, uuid.uuid4())


async def test_running_a_stage_announces_its_start_log_lines_progress_and_end(
    db_session: AsyncSession, admin_user: User
) -> None:
    run = await new_run(db_session, admin_user)

    async def work(ctx) -> None:  # type: ignore[no-untyped-def]
        await ctx.log("working")
        await ctx.progress(0.5)

    stages = [Stage("only", work, 0, 100)]
    redis = FakeRedis()

    await run_stage(db_session, make_settings(), run.id, "only", stages=stages, redis=redis)  # type: ignore[arg-type]

    channels = {channel for channel, _ in redis.published}
    assert channels == {f"run:{run.id}"}
    assert len(redis.published) >= 4  # started, log, progress, finished


def test_every_pipeline_stage_is_known_to_the_run_view() -> None:
    # The web timeline lists these in order; keep it in step when a stage is added.
    assert [s.name for s in STAGES] == ["ingest", "rank", "script", "tts", "mix", "finalize"]
