"""Live view of a run: a Server-Sent Events stream fed by the database, woken by Redis.

The database is the source of truth. Workers and the API only *announce* on a Redis channel
that something about a run changed; the stream then re-reads the run and sends what is new. A
missed announcement (Redis down, a restart) therefore delays an update by at most `POLL_S`, and
a client that reconnects simply gets the current state again.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import structlog
from redis.asyncio import Redis
from redis.asyncio.client import PubSub
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Episode, Run, RunEvent
from byop.models.enums import RunStatus
from byop.schemas.run import RunEventResponse, RunResponse

log = structlog.get_logger(__name__)

ACTIVE = (RunStatus.QUEUED, RunStatus.RUNNING)  # same as the orchestrator's; it imports us

POLL_S = 2.0  # how often the database is checked even without an announcement
HEARTBEAT_S = 15.0  # a comment line so proxies and browsers keep the connection open
MAX_STREAM_S = 3600.0  # after this the client reconnects and receives the current state
RETRY_MS = 3000  # how long the browser waits before reconnecting


def channel(run_id: uuid.UUID) -> str:
    return f"run:{run_id}"


async def announce(redis: Redis | None, run_id: uuid.UUID) -> None:
    """Tell open streams that the run changed. Never fails: the stream polls anyway."""
    if redis is None:
        return
    try:
        await redis.publish(channel(run_id), "1")
    except Exception as exc:  # noqa: BLE001 - a notification must not break the run
        log.debug("run_announce_failed", run_id=str(run_id), error=str(exc))


def sse(event: str, data: object) -> str:
    """One SSE message. JSON never contains a raw newline, so one `data:` line is enough."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def run_payload(run: Run, episode_id: uuid.UUID | None) -> dict[str, Any]:
    response = RunResponse(
        id=run.id,
        show_id=run.show_id,
        trigger=run.trigger,
        status=run.status,
        stage=run.stage,
        progress=run.progress,
        error=run.error,
        cancel_requested=run.cancel_requested,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        episode_id=episode_id,
    )
    return response.model_dump(mode="json")


def event_payload(event: RunEvent) -> dict[str, Any]:
    return RunEventResponse(
        id=event.id,
        ts=event.ts,
        level=event.level,
        stage=event.stage,
        message=event.message,
        data=event.data,
    ).model_dump(mode="json")


async def _load(
    session: AsyncSession,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    cursor: tuple[datetime, uuid.UUID] | None,
) -> tuple[Run | None, uuid.UUID | None, list[RunEvent]]:
    """The run, its episode and the events after `cursor`, in one short transaction."""
    run = await session.scalar(
        select(Run)
        .where(Run.id == run_id, Run.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    if run is None:
        await session.commit()
        return None, None, []
    episode_id = await session.scalar(
        select(Episode.id).where(Episode.run_id == run_id, Episode.user_id == user_id)
    )
    query = select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.user_id == user_id)
    if cursor is not None:
        query = query.where(tuple_(RunEvent.ts, RunEvent.id) > tuple_(*cursor))
    events = list(await session.scalars(query.order_by(RunEvent.ts, RunEvent.id)))
    await session.commit()  # end the transaction so the connection is free while we wait
    return run, episode_id, events


class _Waker:
    """Waits for an announcement or the poll interval, whichever comes first."""

    def __init__(self, redis: Redis | None, run_id: uuid.UUID) -> None:
        self._redis = redis
        self._run_id = run_id
        self._pubsub: PubSub | None = None

    async def start(self) -> None:
        if self._redis is None:
            return
        try:
            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe(channel(self._run_id))
        except Exception as exc:  # noqa: BLE001 - fall back to polling
            log.warning("run_stream_without_redis", error=str(exc))
            self._pubsub = None

    async def wait(self, seconds: float) -> None:
        if self._pubsub is not None:
            try:
                await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=seconds)
                return
            except Exception as exc:  # noqa: BLE001 - Redis went away: poll from now on
                log.warning("run_stream_lost_redis", error=str(exc))
                self._pubsub = None
        await asyncio.sleep(seconds)

    async def close(self) -> None:
        if self._pubsub is not None:
            try:
                await self._pubsub.aclose()  # type: ignore[no-untyped-call]  # redis-py ships it untyped
            except Exception as exc:  # noqa: BLE001 - closing is best effort
                log.debug("run_stream_close_failed", error=str(exc))


async def stream_run(
    session: AsyncSession,
    redis: Redis | None,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    poll_s: float = POLL_S,
    heartbeat_s: float = HEARTBEAT_S,
    max_s: float = MAX_STREAM_S,
) -> AsyncGenerator[str, None]:
    """SSE messages for one run.

    * `snapshot`: the run and its whole log, sent first (also after every reconnect);
    * `update`: the run and the log lines added since the previous message;
    * `done`: the run is no longer waiting or working; the client should close the stream.
    """
    waker = _Waker(redis, run_id)
    await waker.start()  # subscribe first, so nothing announced during the first read is lost
    loop = asyncio.get_running_loop()
    started = last_beat = loop.time()
    try:
        yield f"retry: {RETRY_MS}\n\n"
        run, episode_id, events = await _load(session, user_id, run_id, None)
        if run is None:
            yield sse("gone", {"detail": "Run not found"})
            return
        cursor = (events[-1].ts, events[-1].id) if events else None
        sent = run_payload(run, episode_id)
        status = run.status  # read now: `run` is shared with the session and may change under us
        yield sse("snapshot", {"run": sent, "events": [event_payload(e) for e in events]})
        while status in ACTIVE:
            await waker.wait(min(poll_s, heartbeat_s))
            run, episode_id, events = await _load(session, user_id, run_id, cursor)
            if run is None:
                yield sse("gone", {"detail": "Run not found"})
                return
            current = run_payload(run, episode_id)
            status = run.status
            if events or current != sent:
                cursor = (events[-1].ts, events[-1].id) if events else cursor
                sent = current
                last_beat = loop.time()
                yield sse("update", {"run": current, "events": [event_payload(e) for e in events]})
            elif loop.time() - last_beat >= heartbeat_s:
                last_beat = loop.time()
                yield ": ping\n\n"
            if loop.time() - started >= max_s:
                return  # the client reconnects and gets the state again
        yield sse("done", {"status": status.value})
    finally:
        await waker.close()
