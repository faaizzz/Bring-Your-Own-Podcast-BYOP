"""Pieces shared by every provider family (LLM, TTS)."""

import random
import uuid
from dataclasses import dataclass, field


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
