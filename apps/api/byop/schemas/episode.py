import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from byop.models.enums import EpisodeStatus, RunStatus, RunTrigger
from byop.schemas.script import SegmentKind

MAX_SEGMENTS = 300
SEGMENT_TEXT_MAX = 20_000


class SegmentIn(BaseModel):
    """One turn of speech in the script, as edited."""

    speaker: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=SEGMENT_TEXT_MAX)]
    kind: SegmentKind = "story"
    # Which stories the turn covers; sent back unchanged by the editor.
    item_ids: Annotated[list[str], Field(max_length=50)] = Field(default_factory=list)


class EpisodeUpdate(BaseModel):
    """Fields left out stay as they are. `segments` replaces the whole script."""

    title: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
        | None
    ) = None
    description: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=10_000)] | None
    ) = None
    segments: Annotated[list[SegmentIn], Field(min_length=1, max_length=MAX_SEGMENTS)] | None = None


class EpisodeRunInfo(BaseModel):
    """The run that made (or is re-voicing) the episode."""

    id: uuid.UUID
    trigger: RunTrigger
    status: RunStatus
    stage: str | None
    progress: int
    error: str | None


class EpisodeSource(BaseModel):
    """A story the episode is built from."""

    id: uuid.UUID
    title: str
    url: str
    source_name: str | None
    published_at: datetime | None


class EpisodeSummary(BaseModel):
    id: uuid.UUID
    show_id: uuid.UUID
    title: str
    status: EpisodeStatus
    published_at: datetime | None
    duration_s: int | None
    size_bytes: int | None
    created_at: datetime
    run: EpisodeRunInfo | None


class EpisodeResponse(EpisodeSummary):
    description: str
    segments: list[SegmentIn]
    # Names the editor offers for a segment's speaker.
    speakers: list[str]
    # Each edit of the script bumps `revision`; `audio_revision` is the one the audio was
    # voiced from (None before there is audio). The episode can be approved when they match.
    revision: int
    audio_revision: int | None
    audio_current: bool
    audio_url: str | None
    sources: list[EpisodeSource]
    updated_at: datetime
