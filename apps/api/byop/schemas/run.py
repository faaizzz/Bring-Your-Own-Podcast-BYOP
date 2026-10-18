import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from byop.models.enums import EpisodeStatus, EventLevel, RunStatus, RunTrigger


class RunEventResponse(BaseModel):
    id: uuid.UUID
    ts: datetime
    level: EventLevel
    stage: str | None
    message: str
    # Structured details of the event (counts, titles, ...); free-form JSON.
    data: dict[str, Any] | None = None  # noqa: ANN401 - arbitrary JSON written by stages


class RunResponse(BaseModel):
    id: uuid.UUID
    show_id: uuid.UUID
    trigger: RunTrigger
    status: RunStatus
    stage: str | None
    progress: int
    error: str | None
    cancel_requested: bool
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    # The draft episode this run produced (or is re-voicing), once there is one.
    episode_id: uuid.UUID | None = None


class RunDetail(RunResponse):
    events: list[RunEventResponse] = Field(default_factory=list)
    # Where to open this run's trace in Langfuse; None when it is not traced.
    trace_url: str | None = None


class HistoryRow(BaseModel):
    """One run in the history list, with the episode it made and what it cost."""

    id: uuid.UUID
    show_id: uuid.UUID
    show_title: str
    trigger: RunTrigger
    status: RunStatus
    stage: str | None
    progress: int
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    # Seconds from start to end; None while the run is still going or never started.
    duration_s: int | None
    # Sum of the run's LLM and TTS calls; None when none were recorded.
    cost_usd: Decimal | None
    episode_id: uuid.UUID | None
    episode_title: str | None
    episode_status: EpisodeStatus | None


class HistoryPage(BaseModel):
    items: list[HistoryRow]
    # Pass as `cursor` to get the next page; None on the last one.
    next_cursor: str | None
