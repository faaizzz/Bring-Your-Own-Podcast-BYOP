import enum
import uuid
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from byop.models.enums import SourceKind
from byop.schemas.show import LLMProviderName


class RawCandidate(BaseModel):
    """What the model returns for one source. Loose on purpose: bad entries are dropped later."""

    kind: str
    value: str
    name: str = ""
    reason: str = ""


class RawCandidates(BaseModel):
    """The reply schema sent to the model."""

    candidates: list[RawCandidate] = Field(max_length=60)


class DiscoveredSource(BaseModel):
    """A source worth proposing: RSS feeds and pages were fetched and found usable."""

    kind: SourceKind
    name: str
    value: str
    reason: str
    # Titles of the newest entries, for RSS feeds.
    recent_titles: list[str] = Field(default_factory=list)


class DiscoveryStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class DiscoveryJob(BaseModel):
    job_id: str
    status: DiscoveryStatus
    show_id: uuid.UUID | None = None
    candidates: list[DiscoveredSource] = Field(default_factory=list)
    error: str | None = None


class DiscoveryStarted(BaseModel):
    job_id: str


class DraftDiscoverRequest(BaseModel):
    """Discovery before the show exists (the create wizard)."""

    topic: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
    language: Annotated[str, StringConstraints(strip_whitespace=True, max_length=16)] | None = None
    llm_provider: LLMProviderName | None = None
    llm_model: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = (
        None
    )
