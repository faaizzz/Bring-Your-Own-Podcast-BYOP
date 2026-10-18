"""Pieces shared by every provider family (LLM, TTS)."""

import random
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol


@dataclass(frozen=True)
class CallMetadata:
    """Who is calling and why; carried on every call so usage capture and tracing can hook in."""

    run_id: uuid.UUID | None = None
    show_id: uuid.UUID | None = None
    stage: str | None = None
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff with jitter for 429 / 5xx / network errors."""

    max_attempts: int = 4
    initial_wait_s: float = 1.0
    max_wait_s: float = 30.0


def backoff_seconds(policy: RetryPolicy, attempt: int, retry_after: str | None = None) -> float:
    """Seconds to wait before retry number `attempt` (1-based), honouring `Retry-After`."""
    base: float = min(policy.initial_wait_s * 2 ** (attempt - 1), policy.max_wait_s)
    wait: float = base * random.uniform(0.5, 1.0)  # noqa: S311  # jitter, not security
    if retry_after:
        try:
            wait = max(wait, min(float(retry_after), policy.max_wait_s))
        except ValueError:
            pass  # an HTTP-date form: the computed backoff is fine
    return wait


@dataclass(frozen=True)
class UsageRecord:
    """What one billable call used. Providers report it; `services/usage.py` prices it."""

    kind: Literal["llm", "tts"]
    provider: str
    model: str | None
    stage: str | None
    run_id: uuid.UUID | None
    show_id: uuid.UUID | None
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    characters: int | None = None
    # What the provider itself says the call cost (OpenRouter does); None when it does not.
    cost_usd: Decimal | None = None
    # For tracing only (never stored in the database): when the call began, what was sent and
    # what came back (language models), and the call's tags such as the speaker of a voice.
    started_at: datetime | None = None
    prompt: str | None = None
    completion: str | None = None
    tags: dict[str, str] = field(default_factory=dict)


class UsageSink(Protocol):
    def record(self, usage: UsageRecord) -> None: ...


_sink: ContextVar[UsageSink | None] = ContextVar("byop_usage_sink", default=None)


def set_usage_sink(sink: UsageSink | None) -> Token[UsageSink | None]:
    """Make `sink` receive the usage of every provider call made in this context (and in tasks
    started from it) until `reset_usage_sink`."""
    return _sink.set(sink)


def reset_usage_sink(token: Token[UsageSink | None]) -> None:
    _sink.reset(token)


def current_usage_sink() -> UsageSink | None:
    return _sink.get()


def record_usage(usage: UsageRecord) -> None:
    """Hand a finished call's usage to whoever is collecting it (nobody, outside a run)."""
    sink = _sink.get()
    if sink is not None:
        sink.record(usage)
