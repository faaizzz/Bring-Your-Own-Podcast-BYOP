import enum
import uuid
from typing import Annotated, Literal

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
    # Caveats that do not stop discovery, e.g. that web search could not be confirmed.
    warnings: list[str] = Field(default_factory=list)


class DiscoveryStarted(BaseModel):
    job_id: str
    warnings: list[str] = Field(default_factory=list)


class DiscoveryModel(BaseModel):
    """The model discovery would use now and whether it can search the web."""

    provider: str
    provider_label: str
    model: str
    # Where it comes from: DISCOVERY_LLM_*, the show's own choice, or the instance default.
    source: Literal["discovery_setting", "show", "default"]
    web_search: Literal["yes", "no", "unknown"]
    # Why discovery would be refused (`no`) or what could not be confirmed (`unknown`).
    message: str | None = None


class DraftDiscoverRequest(BaseModel):
    """Discovery before the show exists (the create wizard)."""

    topic: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
    language: Annotated[str, StringConstraints(strip_whitespace=True, max_length=16)] | None = None
    llm_provider: LLMProviderName | None = None
    llm_model: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = (
        None
    )
