"""Recording what every LLM and TTS call used and cost.

Providers announce each finished call through `record_usage` (see `byop.providers.common`); a
`UsageCollector` receives them in memory and its owner writes them to `usage_events` with
`flush`, from its own task and session. Doing it this way keeps providers free of the database
and keeps writes out of the concurrent TTS workers.

Inside a run, `run_stage` collects for the whole stage and writes after it (and on every
progress update, so a long stage's spend shows up as it goes). Anywhere else (source discovery,
voice previews) wrap the work in `capture_usage`.
"""

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import structlog
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Run, UsageEvent
from byop.models.enums import UsageKind
from byop.providers.common import (
    UsageRecord,
    current_usage_sink,
    reset_usage_sink,
    set_usage_sink,
)
from byop.services.pricing import price_book

log = structlog.get_logger(__name__)


class UsageCollector:
    """Holds the usage reported while it is the active sink, until it is written."""

    def __init__(self, listener: Callable[[UsageRecord], None] | None = None) -> None:
        self._pending: list[UsageRecord] = []
        self._notices: list[str] = []
        self._listener = listener  # e.g. a tracer that wants to see the same calls

    def record(self, usage: UsageRecord) -> None:
        self._pending.append(usage)
        if self._listener is not None:
            try:
                self._listener(usage)
            except Exception:  # noqa: BLE001 - observers must never break the call they observe
                log.warning("usage_listener_failed", exc_info=True)

    def notice(self, message: str) -> None:
        """Something to tell the user, e.g. a wait for a rate limit (see `NoticeSink`)."""
        self._notices.append(message)

    def take_notices(self) -> list[str]:
        """The notices collected since the last call; the run writes them to its log."""
        taken, self._notices = self._notices, []
        return taken

    @property
    def pending(self) -> int:
        return len(self._pending)

    async def flush(self, session: AsyncSession, user_id: uuid.UUID) -> int:
        """Price and store what has been collected; returns how many events were written.

        Commits the session. If that fails the records stay pending for the next attempt.
        """
        if not self._pending:
            return 0
        batch = list(self._pending)
        prices = await price_book(session, user_id)
        for usage in batch:
            cost, source = prices.cost(usage)
            session.add(
                UsageEvent(
                    user_id=user_id,
                    run_id=usage.run_id,
                    show_id=usage.show_id,
                    kind=UsageKind(usage.kind),
                    provider=usage.provider,
                    model=usage.model,
                    stage=usage.stage,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    characters=usage.characters,
                    cost_usd=cost,
                    cost_source=source,
                    latency_ms=usage.latency_ms,
                )
            )
        await session.commit()
        del self._pending[: len(batch)]
        return len(batch)


def take_current_notices() -> list[str]:
    """The notices of the active collector (nothing when none is collecting)."""
    sink = current_usage_sink()
    return sink.take_notices() if isinstance(sink, UsageCollector) else []


async def flush_current(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Write what the active collector holds; a no-op when nothing is collecting or pending."""
    sink = current_usage_sink()
    if isinstance(sink, UsageCollector) and sink.pending:
        await sink.flush(session, user_id)


@asynccontextmanager
async def capture_usage(session: AsyncSession, user_id: uuid.UUID) -> AsyncIterator[UsageCollector]:
    """Collect the usage of provider calls made inside the block and write it afterwards, also
    when the block fails. Inside another capture (a run) it joins that one."""
    outer = current_usage_sink()
    if isinstance(outer, UsageCollector):
        yield outer
        return
    collector = UsageCollector()
    token = set_usage_sink(collector)
    try:
        yield collector
    finally:
        reset_usage_sink(token)
        try:
            await collector.flush(session, user_id)
        except Exception:
            # Losing a usage row must never hide the real outcome (or error) of the work.
            log.warning("usage_flush_failed", exc_info=True)
            await session.rollback()


async def refresh_run_totals(session: AsyncSession, run: Run) -> None:
    """Set the run's cost fields to the sums of its events (the caller commits)."""
    llm = func.coalesce(
        func.sum(case((UsageEvent.kind == UsageKind.LLM, UsageEvent.cost_usd), else_=0)), 0
    )
    tts = func.coalesce(
        func.sum(case((UsageEvent.kind == UsageKind.TTS, UsageEvent.cost_usd), else_=0)), 0
    )
    row = (
        await session.execute(
            select(llm, tts).where(UsageEvent.run_id == run.id, UsageEvent.user_id == run.user_id)
        )
    ).one()
    run.llm_cost_usd, run.tts_cost_usd = row[0], row[1]
    run.cost_usd = row[0] + row[1]
