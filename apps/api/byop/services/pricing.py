"""What a call costs when the provider does not say: the shipped price table plus the user's
own overrides.

Order of trust, applied by `PriceBook.cost`: the provider's own figure, then the user's override,
then the shipped table, otherwise the cost is unknown (recorded as 0 and marked `unknown`).
"""

import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import PriceOverride
from byop.models.enums import CostSource, UsageKind
from byop.providers.common import UsageRecord

PRICING_FILE = Path(__file__).resolve().parent.parent / "pricing.yaml"
MILLION = Decimal(1_000_000)
CENT_FRACTION = Decimal("0.000001")


@dataclass(frozen=True)
class LLMPrice:
    input_per_million: Decimal
    output_per_million: Decimal


def _money(value: object) -> Decimal:
    return Decimal(str(value))


def _round(amount: Decimal) -> Decimal:
    return amount.quantize(CENT_FRACTION, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PriceBook:
    """Prices by name. TTS names are `provider` or `provider:model`."""

    llm: dict[str, LLMPrice] = field(default_factory=dict)
    tts: dict[str, Decimal] = field(default_factory=dict)

    def llm_price(self, model: str | None) -> LLMPrice | None:
        if not model:
            return None
        if model in self.llm:
            return self.llm[model]
        best: str | None = None
        for key in self.llm:
            rest = model.removeprefix(key)
            if (
                rest != model
                and rest[:1] in {"-", ":", "@", "."}
                and (best is None or len(key) > len(best))
            ):
                best = key
        return self.llm[best] if best else None

    def tts_price(self, provider: str, model: str | None) -> Decimal | None:
        if model and f"{provider}:{model}" in self.tts:
            return self.tts[f"{provider}:{model}"]
        return self.tts.get(provider)

    def cost(self, usage: UsageRecord) -> tuple[Decimal, CostSource]:
        """The cost of one call and where the figure comes from."""
        if usage.cost_usd is not None:
            return _round(usage.cost_usd), CostSource.PROVIDER
        if usage.kind == "llm":
            price = self.llm_price(usage.model)
            if price is None:
                return Decimal(0), CostSource.UNKNOWN
            amount = (
                Decimal(usage.input_tokens or 0) * price.input_per_million
                + Decimal(usage.output_tokens or 0) * price.output_per_million
            ) / MILLION
            return _round(amount), CostSource.PRICE_TABLE
        per_million = self.tts_price(usage.provider, usage.model)
        if per_million is None or usage.characters is None:
            return Decimal(0), CostSource.UNKNOWN
        return _round(Decimal(usage.characters) * per_million / MILLION), CostSource.PRICE_TABLE


def parse_prices(document: dict[str, Any]) -> PriceBook:
    llm = {
        str(model): LLMPrice(_money(entry["input"]), _money(entry["output"]))
        for model, entry in (document.get("llm") or {}).items()
    }
    tts: dict[str, Decimal] = {}
    for provider, entry in (document.get("tts") or {}).items():
        if entry.get("per_million_chars") is not None:
            tts[str(provider)] = _money(entry["per_million_chars"])
        for model, price in (entry.get("models") or {}).items():
            tts[f"{provider}:{model}"] = _money(price)
    return PriceBook(llm, tts)


@lru_cache
def default_prices() -> PriceBook:
    """The shipped table (`byop/pricing.yaml`)."""
    return parse_prices(yaml.safe_load(PRICING_FILE.read_text(encoding="utf-8")) or {})


def apply_overrides(base: PriceBook, overrides: list[PriceOverride]) -> PriceBook:
    llm, tts = dict(base.llm), dict(base.tts)
    for row in overrides:
        if row.kind is UsageKind.LLM:
            if row.input_per_million is not None and row.output_per_million is not None:
                llm[row.name] = LLMPrice(row.input_per_million, row.output_per_million)
        elif row.per_million_chars is not None:
            tts[row.name] = row.per_million_chars
    return PriceBook(llm, tts)


async def list_overrides(session: AsyncSession, user_id: uuid.UUID) -> list[PriceOverride]:
    rows = await session.scalars(
        select(PriceOverride)
        .where(PriceOverride.user_id == user_id)
        .order_by(PriceOverride.kind, PriceOverride.name)
    )
    return list(rows)


async def price_book(session: AsyncSession, user_id: uuid.UUID) -> PriceBook:
    """The prices for this user: the shipped table with their overrides on top."""
    return apply_overrides(default_prices(), await list_overrides(session, user_id))
