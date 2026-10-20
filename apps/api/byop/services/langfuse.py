"""Langfuse tracing of runs, over Langfuse's public HTTP ingestion API.

A run is one trace (named after the show, grouped into a session per show). Each stage that runs
is a span; every language-model call inside it is a *generation* (model, prompt, output, tokens,
cost) and every voice call is a span (characters, cost, latency). Nothing here may ever make a run
fail or wait for long: events are collected in memory, sent once per stage with a short timeout,
and any problem is logged and dropped. Without Langfuse credentials the tracer does nothing.

The calls come from the usage reports providers already make (`record_usage`), so no pipeline code
changed to support tracing.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Run, Show
from byop.models.enums import CredentialProvider
from byop.providers.common import UsageRecord
from byop.services.credentials import (
    CredentialDecryptionError,
    CredentialResolver,
    ProviderConfig,
    ProviderNotConfigured,
)
from byop.services.pricing import PriceBook, price_book

log = structlog.get_logger(__name__)

SEND_TIMEOUT_S = 4.0
BATCH_SIZE = 100
MAX_TEXT_CHARS = 20_000  # prompts and answers are cut here; the trace is not an archive


class Tracer(Protocol):
    """What the pipeline needs from a tracer."""

    def record(self, usage: UsageRecord) -> None: ...

    async def start(self) -> None: ...

    async def finish(
        self, outcome: str, message: str | None = None, *, last: bool = False
    ) -> None: ...


class NoopTracer:
    """Used when Langfuse is not configured."""

    def record(self, usage: UsageRecord) -> None:
        return None

    async def start(self) -> None:
        return None

    async def finish(self, outcome: str, message: str | None = None, *, last: bool = False) -> None:
        return None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _cut(text: str | None) -> str | None:
    if text is None or len(text) <= MAX_TEXT_CHARS:
        return text
    return text[:MAX_TEXT_CHARS] + f"… [{len(text) - MAX_TEXT_CHARS} more characters]"


def span_id(run_id: uuid.UUID, stage: str) -> str:
    """The same stage of the same run always has the same span id, so a retried stage updates
    its span instead of adding another."""
    return str(uuid.uuid5(run_id, f"stage:{stage}"))


@dataclass
class LangfuseTracer:
    """Collects the events of one stage and sends them. It copies what it needs from the run and
    show up front: their ORM objects expire when a stage ends badly and must not be read later."""

    config: ProviderConfig
    stage: str
    prices: PriceBook
    trace_id: str
    run_id: uuid.UUID
    show_id: uuid.UUID | None
    show_title: str
    show_slug: str
    style: str
    trigger: str
    created_at: str
    http: httpx.AsyncClient | None = None
    _events: list[dict[str, object]] = field(default_factory=list)
    _dead: bool = False

    def _event(self, kind: str, body: dict[str, object], timestamp: str | None = None) -> None:
        self._events.append(
            {
                "id": str(uuid.uuid4()),
                "type": kind,
                "timestamp": timestamp or _now(),
                "body": body,
            }
        )

    # -- what the pipeline reports ---------------------------------------------------------

    async def start(self) -> None:
        self._event(
            "trace-create",
            {
                "id": self.trace_id,
                "name": self.show_title,
                # Work outside a show (designing a style) is not part of a show's session.
                "sessionId": str(self.show_id) if self.show_id else None,
                "tags": [tag for tag in (self.trigger, self.style) if tag],
                "metadata": {
                    "run_id": str(self.run_id),
                    "show_id": str(self.show_id) if self.show_id else None,
                    "slug": self.show_slug,
                },
                "timestamp": self.created_at,
            },
        )
        self._event(
            "span-create",
            {
                "id": span_id(self.run_id, self.stage),
                "traceId": self.trace_id,
                "name": self.stage,
                "startTime": _now(),
            },
        )
        await self._send()

    def record(self, usage: UsageRecord) -> None:
        """A finished call: a generation for a language model, a span for a voice."""
        ended = datetime.now(UTC)
        started = usage.started_at or ended - timedelta(milliseconds=usage.latency_ms)
        cost, source = self.prices.cost(usage)
        parent = span_id(self.run_id, self.stage)
        common: dict[str, object] = {
            "id": str(uuid.uuid4()),
            "traceId": self.trace_id,
            "parentObservationId": parent,
            "startTime": started.isoformat(),
            "endTime": ended.isoformat(),
        }
        if usage.kind == "llm":
            total = (usage.input_tokens or 0) + (usage.output_tokens or 0)
            body: dict[str, object] = {
                **common,
                "name": usage.stage or "llm",
                "model": usage.model,
                "input": _cut(usage.prompt),
                "output": _cut(usage.completion),
                "usageDetails": {
                    "input": usage.input_tokens or 0,
                    "output": usage.output_tokens or 0,
                    "total": total,
                },
                "metadata": {"provider": usage.provider, "cost_source": source.value, **usage.tags},
            }
            if source.value != "unknown":
                body["costDetails"] = {"total": float(cost)}
            self._event("generation-create", body, started.isoformat())
        else:
            self._event(
                "span-create",
                {
                    **common,
                    "name": f"tts {usage.provider}",
                    "metadata": {
                        "provider": usage.provider,
                        "characters": usage.characters,
                        "cost_usd": str(cost) if source.value != "unknown" else None,
                        "cost_source": source.value,
                        "latency_ms": usage.latency_ms,
                        **usage.tags,
                    },
                },
                started.isoformat(),
            )

    async def finish(self, outcome: str, message: str | None = None, *, last: bool = False) -> None:
        """Close the stage's span; `outcome` is `ok`, `retry`, `failed` or `cancelled`. When the
        run is over (`last`, or it failed or was cancelled) the trace gets its result as well."""
        failed = outcome == "failed"
        update: dict[str, object] = {
            "id": span_id(self.run_id, self.stage),
            "traceId": self.trace_id,
            "endTime": _now(),
            "level": "ERROR" if failed else ("DEFAULT" if outcome == "ok" else "WARNING"),
        }
        if message:
            update["statusMessage"] = message[:1000]
        self._event("span-update", update)
        if last or outcome in ("failed", "cancelled"):
            self._event(
                "trace-create",
                {
                    "id": self.trace_id,
                    "output": message or ("Run finished" if outcome == "ok" else outcome),
                    "metadata": {"status": outcome},
                },
            )
        await self._send()

    # -- sending ---------------------------------------------------------------------------

    async def _send(self) -> None:
        events, self._events = self._events, []
        if not events or self._dead:
            return
        key = self.config.api_key.get_secret_value() if self.config.api_key else ""
        auth = httpx.BasicAuth(self.config.extra.get("public_key", ""), key)
        url = f"{(self.config.base_url or '').rstrip('/')}/api/public/ingestion"
        client = self.http or httpx.AsyncClient(timeout=SEND_TIMEOUT_S)
        try:
            for start in range(0, len(events), BATCH_SIZE):
                response = await client.post(
                    url, json={"batch": events[start : start + BATCH_SIZE]}, auth=auth
                )
                if response.status_code >= 400:
                    log.warning("langfuse_rejected_events", status=response.status_code)
                    if response.status_code in (401, 403):
                        self._dead = True  # wrong keys: do not keep trying within this stage
                        return
        except Exception as exc:  # noqa: BLE001 - tracing must never fail a run
            self._dead = True
            log.warning("langfuse_unreachable", error=type(exc).__name__)
        finally:
            if self.http is None:
                await client.aclose()


async def open_tracer(
    session: AsyncSession,
    resolver: CredentialResolver,
    run: Run,
    show: Show,
    stage: str,
    *,
    http: httpx.AsyncClient | None = None,
) -> Tracer:
    """The tracer for one stage of a run: Langfuse when it is set up, else one that does nothing.
    Gives the run its `trace_id` the first time."""
    try:
        config = await resolver.get(run.user_id, CredentialProvider.LANGFUSE)
    except (ProviderNotConfigured, CredentialDecryptionError):
        return NoopTracer()
    except Exception:
        log.warning("langfuse_config_failed", exc_info=True)
        return NoopTracer()
    if config.api_key is None or not config.extra.get("public_key") or not config.base_url:
        return NoopTracer()
    if run.trace_id is None:
        run.trace_id = uuid.uuid4().hex
        await session.commit()
    assert run.trace_id is not None
    return LangfuseTracer(
        config=config,
        stage=stage,
        prices=await price_book(session, run.user_id),
        trace_id=run.trace_id,
        run_id=run.id,
        show_id=show.id,
        show_title=show.title,
        show_slug=show.slug,
        style=show.style.value,
        trigger=run.trigger.value,
        created_at=run.created_at.isoformat(),
        http=http,
    )


async def open_assist_tracer(
    session: AsyncSession, resolver: CredentialResolver, user_id: uuid.UUID, kind: str
) -> Tracer:
    """A tracer for one call that belongs to no run, such as designing a style: its own trace.
    Langfuse when it is set up, else one that does nothing."""
    try:
        config = await resolver.get(user_id, CredentialProvider.LANGFUSE)
    except (ProviderNotConfigured, CredentialDecryptionError):
        return NoopTracer()
    except Exception:
        log.warning("langfuse_config_failed", exc_info=True)
        return NoopTracer()
    if config.api_key is None or not config.extra.get("public_key") or not config.base_url:
        return NoopTracer()
    return LangfuseTracer(
        config=config,
        stage="assist",
        prices=await price_book(session, user_id),
        trace_id=uuid.uuid4().hex,
        run_id=uuid.uuid4(),  # only names the span the call hangs under
        show_id=None,
        show_title=f"Assist: {kind}",
        show_slug="",
        style="",
        trigger="assist",
        created_at=_now(),
    )


def trace_url(
    config: ProviderConfig | None, public_url: str | None, trace_id: str | None
) -> str | None:
    """Where to open the trace in the Langfuse web UI."""
    if config is None or trace_id is None:
        return None
    base = (public_url or config.base_url or "").rstrip("/")
    return f"{base}/trace/{trace_id}" if base else None
