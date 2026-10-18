import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from byop.models.enums import EventLevel, RunStatus, RunTrigger


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


class RunDetail(RunResponse):
    events: list[RunEventResponse] = Field(default_factory=list)
