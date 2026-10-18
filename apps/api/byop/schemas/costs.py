import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from byop.models.enums import UsageKind

GroupBy = Literal["show", "month", "provider", "stage"]


class CostGroup(BaseModel):
    """The spend of one show, month, provider or stage."""

    key: str
    label: str
    cost_usd: Decimal
    llm_cost_usd: Decimal
    tts_cost_usd: Decimal
    calls: int
    # Calls whose price could not be found; their cost is counted as 0, so the total is a floor.
    unknown_calls: int
    input_tokens: int
    output_tokens: int
    characters: int


class CostSummary(BaseModel):
    group_by: GroupBy
    from_date: date | None = Field(serialization_alias="from")
    to_date: date | None = Field(serialization_alias="to")
    total: CostGroup
    groups: list[CostGroup]
    # Runs in the period that produced an episode, and what such a run cost on average
    # (None when there was none).
    episodes: int
    avg_episode_cost_usd: Decimal | None


class UsageLine(BaseModel):
    """What one kind of call used within a run: one row per stage, model and provider."""

    stage: str | None
    kind: UsageKind
    provider: str
    model: str | None
    calls: int
    unknown_calls: int
    input_tokens: int
    output_tokens: int
    characters: int
    cost_usd: Decimal


class PriceEntry(BaseModel):
    kind: UsageKind
    # LLM: the model id. TTS: the provider ("openai") or a model of it ("openai:tts-1-hd").
    name: str
    input_per_million: Decimal | None = None
    output_per_million: Decimal | None = None
    per_million_chars: Decimal | None = None
    # Where the price comes from: the shipped table, or the user's own override.
    source: Literal["default", "override"]


class PriceOverrideIn(BaseModel):
    kind: UsageKind
    name: str = Field(min_length=1, max_length=200)
    input_per_million: Decimal | None = Field(default=None, ge=0, le=1_000_000)
    output_per_million: Decimal | None = Field(default=None, ge=0, le=1_000_000)
    per_million_chars: Decimal | None = Field(default=None, ge=0, le=100_000_000)


class CostEstimate(BaseModel):
    show_id: uuid.UUID
    # None when the price of the model or voice is not known; `notes` says which.
    llm_usd: Decimal | None
    tts_usd: Decimal | None
    total_usd: Decimal | None
    characters: int
    input_tokens: int
    output_tokens: int
    model: str | None
    notes: list[str]
