"""Spend overviews and the estimate for the next episode, from `usage_events` and the prices."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings
from byop.models import Run, Show, Speaker, UsageEvent
from byop.models.enums import CostSource, RunStatus, UsageKind
from byop.providers.llm import UnsupportedLLMProvider, get_llm
from byop.schemas.costs import CostEstimate, CostGroup, CostSummary, GroupBy, UsageLine
from byop.services.credentials import (
    CredentialDecryptionError,
    CredentialResolver,
    ProviderNotConfigured,
)
from byop.services.llm_choice import show_model
from byop.services.models import list_models_cached
from byop.services.pricing import MILLION, PriceBook, price_book

UNKNOWN_SHOW = "Deleted show"
# Plan-the-episode assumptions for the estimate. Rough on purpose: the real numbers depend on
# the stories and on how long the model talks, and the page says so.
CHARS_PER_MINUTE = 900  # about 150 spoken words
CHARS_PER_TOKEN = 4
RANK_INPUT_TOKENS = 6_000
RANK_OUTPUT_TOKENS = 600
SCRIPT_BASE_INPUT_TOKENS = 1_500
STORY_INPUT_TOKENS = 600
SCRIPT_OVERHEAD_OUTPUT_TOKENS = 400


def _group_columns() -> list[Any]:  # SQLAlchemy column expressions
    llm = case((UsageEvent.kind == UsageKind.LLM, UsageEvent.cost_usd), else_=0)
    tts = case((UsageEvent.kind == UsageKind.TTS, UsageEvent.cost_usd), else_=0)
    unknown = case((UsageEvent.cost_source == CostSource.UNKNOWN, 1), else_=0)
    return [
        func.coalesce(func.sum(UsageEvent.cost_usd), 0),
        func.coalesce(func.sum(llm), 0),
        func.coalesce(func.sum(tts), 0),
        func.count(),
        func.coalesce(func.sum(unknown), 0),
        func.coalesce(func.sum(UsageEvent.input_tokens), 0),
        func.coalesce(func.sum(UsageEvent.output_tokens), 0),
        func.coalesce(func.sum(UsageEvent.characters), 0),
    ]


def _group(key: str, label: str, values: tuple[object, ...]) -> CostGroup:
    cost, llm, tts, calls, unknown, tokens_in, tokens_out, chars = values
    return CostGroup(
        key=key,
        label=label,
        cost_usd=Decimal(str(cost)),
        llm_cost_usd=Decimal(str(llm)),
        tts_cost_usd=Decimal(str(tts)),
        calls=int(calls),  # type: ignore[call-overload]
        unknown_calls=int(unknown),  # type: ignore[call-overload]
        input_tokens=int(tokens_in),  # type: ignore[call-overload]
        output_tokens=int(tokens_out),  # type: ignore[call-overload]
        characters=int(chars),  # type: ignore[call-overload]
    )


def _in_range(query: Any, start: date | None, end: date | None) -> Any:  # a Select
    if start is not None:
        query = query.where(UsageEvent.created_at >= datetime.combine(start, time.min, UTC))
    if end is not None:
        query = query.where(
            UsageEvent.created_at < datetime.combine(end + timedelta(days=1), time.min, UTC)
        )
    return query


async def cost_summary(
    session: AsyncSession,
    user_id: uuid.UUID,
    group_by: GroupBy,
    start: date | None = None,
    end: date | None = None,
) -> CostSummary:
    """Spend per show, calendar month (UTC), provider or stage, biggest first (months oldest
    first). Days are inclusive."""
    columns = _group_columns()
    base = select(*columns).where(UsageEvent.user_id == user_id)
    total_row = (await session.execute(_in_range(base, start, end))).one()

    if group_by == "show":
        rows = await session.execute(
            _in_range(select(UsageEvent.show_id, Show.title, *columns), start, end)
            .outerjoin(Show, Show.id == UsageEvent.show_id)
            .where(UsageEvent.user_id == user_id)
            .group_by(UsageEvent.show_id, Show.title)
        )
        groups = [
            _group(str(show_id) if show_id else "", title or UNKNOWN_SHOW, tuple(values))
            for show_id, title, *values in rows.all()
        ]
    else:
        key_col: Any = {
            "month": func.to_char(func.timezone("UTC", UsageEvent.created_at), "YYYY-MM"),
            "provider": UsageEvent.provider,
            "stage": func.coalesce(UsageEvent.stage, ""),
        }[group_by]
        rows = await session.execute(
            _in_range(select(key_col, *columns), start, end)
            .where(UsageEvent.user_id == user_id)
            .group_by(key_col)
        )
        groups = [
            _group(str(key), str(key) or "(none)", tuple(values)) for key, *values in rows.all()
        ]
    if group_by == "month":
        groups.sort(key=lambda g: g.key)
    else:
        groups.sort(key=lambda g: (-g.cost_usd, g.label))
    episodes, average = await _episode_average(session, user_id, start, end)
    return CostSummary(
        group_by=group_by,
        from_date=start,
        to_date=end,
        total=_group("total", "Total", tuple(total_row)),
        groups=groups,
        episodes=episodes,
        avg_episode_cost_usd=average,
    )


async def _episode_average(
    session: AsyncSession, user_id: uuid.UUID, start: date | None, end: date | None
) -> tuple[int, Decimal | None]:
    """How many runs made an episode in the period and their mean cost (from the run totals)."""
    query = select(func.count(), func.avg(Run.cost_usd)).where(
        Run.user_id == user_id,
        Run.status.in_((RunStatus.SUCCEEDED, RunStatus.AWAITING_REVIEW)),
    )
    if start is not None:
        query = query.where(Run.created_at >= datetime.combine(start, time.min, UTC))
    if end is not None:
        query = query.where(
            Run.created_at < datetime.combine(end + timedelta(days=1), time.min, UTC)
        )
    count, average = (await session.execute(query)).one()
    return int(count), (Decimal(str(average)) if average is not None else None)


async def run_usage(
    session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID
) -> list[UsageLine]:
    """A run's calls grouped by stage, kind, provider and model, in the order the stages run."""
    unknown = case((UsageEvent.cost_source == CostSource.UNKNOWN, 1), else_=0)
    rows = await session.execute(
        select(
            UsageEvent.stage,
            UsageEvent.kind,
            UsageEvent.provider,
            UsageEvent.model,
            func.count(),
            func.coalesce(func.sum(unknown), 0),
            func.coalesce(func.sum(UsageEvent.input_tokens), 0),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0),
            func.coalesce(func.sum(UsageEvent.characters), 0),
            func.coalesce(func.sum(UsageEvent.cost_usd), 0),
        )
        .where(UsageEvent.run_id == run_id, UsageEvent.user_id == user_id)
        .group_by(UsageEvent.stage, UsageEvent.kind, UsageEvent.provider, UsageEvent.model)
        .order_by(func.min(UsageEvent.created_at), UsageEvent.provider)
    )
    return [
        UsageLine(
            stage=stage,
            kind=kind,
            provider=provider,
            model=model,
            calls=int(calls),
            unknown_calls=int(unknown_calls),
            input_tokens=int(tokens_in),
            output_tokens=int(tokens_out),
            characters=int(chars),
            cost_usd=Decimal(str(cost)),
        )
        for (
            stage,
            kind,
            provider,
            model,
            calls,
            unknown_calls,
            tokens_in,
            tokens_out,
            chars,
            cost,
        ) in rows.all()
    ]


CSV_HEADER = (
    "created_at",
    "show",
    "run_id",
    "stage",
    "kind",
    "provider",
    "model",
    "input_tokens",
    "output_tokens",
    "characters",
    "cost_usd",
    "cost_source",
    "latency_ms",
)
CSV_BATCH = 1000


def csv_cell(value: object) -> str:
    """A cell that a spreadsheet will not run as a formula (show titles are user text)."""
    text = "" if value is None else str(value)
    return f"'{text}" if text[:1] in {"=", "+", "-", "@", "\t", "\r"} else text


async def usage_csv_rows(
    session: AsyncSession, user_id: uuid.UUID, start: date | None, end: date | None
) -> AsyncIterator[list[str]]:
    """The usage events of the period, oldest first, one CSV row at a time."""
    query = (
        select(UsageEvent, Show.title)
        .outerjoin(Show, Show.id == UsageEvent.show_id)
        .where(UsageEvent.user_id == user_id)
        .order_by(UsageEvent.created_at, UsageEvent.id)
        .execution_options(yield_per=CSV_BATCH)
    )
    query = _in_range(query, start, end)
    yield list(CSV_HEADER)
    result = await session.stream(query)
    async for event, title in result:
        yield [
            event.created_at.astimezone(UTC).isoformat(),
            csv_cell(title or ""),
            str(event.run_id or ""),
            csv_cell(event.stage),
            event.kind.value,
            csv_cell(event.provider),
            csv_cell(event.model),
            "" if event.input_tokens is None else str(event.input_tokens),
            "" if event.output_tokens is None else str(event.output_tokens),
            "" if event.characters is None else str(event.characters),
            str(event.cost_usd),
            event.cost_source.value,
            "" if event.latency_ms is None else str(event.latency_ms),
        ]


# --- estimate ------------------------------------------------------------------------------------


def _estimate_tts(
    speakers: list[Speaker], characters: int, prices: PriceBook, notes: list[str]
) -> Decimal | None:
    if not speakers:
        notes.append("The show has no speakers yet, so the voice cost is unknown.")
        return None
    per_speaker = Decimal(characters) / len(speakers)
    total = Decimal(0)
    for speaker in speakers:
        model = speaker.voice_params.get("model")
        price = prices.tts_price(speaker.tts_provider, model if isinstance(model, str) else None)
        if price is None:
            notes.append(f"No price is known for {speaker.tts_provider} voices.")
            return None
        total += per_speaker * price / MILLION
    return total


async def estimate_episode(
    session: AsyncSession,
    settings: Settings,
    user_id: uuid.UUID,
    show: Show,
    *,
    extra_llm_price: tuple[Decimal, Decimal] | None = None,
) -> CostEstimate:
    """What one episode of `show` is expected to cost, from its length, model and voices.

    `extra_llm_price` is the model's (input, output) price per 1M tokens from the provider's own
    model list, used when the price table does not know the model.
    """
    prices = await price_book(session, user_id)
    notes = [
        f"Assumes about {CHARS_PER_MINUTE} spoken characters per minute and "
        f"{show.items_per_episode} stories; real costs vary with the stories."
    ]
    characters = show.target_minutes * CHARS_PER_MINUTE
    input_tokens = (
        RANK_INPUT_TOKENS + SCRIPT_BASE_INPUT_TOKENS + show.items_per_episode * STORY_INPUT_TOKENS
    )
    output_tokens = (
        RANK_OUTPUT_TOKENS + SCRIPT_OVERHEAD_OUTPUT_TOKENS + characters * 6 // (5 * CHARS_PER_TOKEN)
    )

    chosen = show_model(settings, show)
    llm_usd: Decimal | None = None
    model: str | None = None
    if chosen is None:
        notes.append("No language model is set up for this show.")
    else:
        model = chosen[1]
        price = prices.llm_price(model)
        if price is not None:
            rates: tuple[Decimal, Decimal] | None = (
                price.input_per_million,
                price.output_per_million,
            )
        else:
            rates = extra_llm_price
        if rates is None:
            notes.append(f"No price is known for {model}; set one under Settings › Pricing.")
        else:
            llm_usd = (input_tokens * rates[0] + output_tokens * rates[1]) / MILLION

    speakers = list(
        await session.scalars(
            select(Speaker)
            .where(Speaker.show_id == show.id, Speaker.user_id == user_id)
            .order_by(Speaker.position)
        )
    )
    tts_usd = _estimate_tts(speakers, characters, prices, notes)
    known = [v for v in (llm_usd, tts_usd) if v is not None]
    return CostEstimate(
        show_id=show.id,
        llm_usd=llm_usd,
        tts_usd=tts_usd,
        total_usd=sum(known, Decimal(0)) if len(known) == 2 else None,
        characters=characters,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
        notes=notes,
    )


async def provider_llm_price(
    resolver: CredentialResolver, redis: Redis, settings: Settings, user_id: uuid.UUID, show: Show
) -> tuple[Decimal, Decimal] | None:
    """The show model's (input, output) price per 1M tokens from its provider's model list, for
    providers that publish one (OpenRouter); None when unknown or unreachable."""
    chosen = show_model(settings, show)
    if chosen is None:
        return None
    provider, model = chosen
    try:
        config = await resolver.get(user_id, provider)
        llm = get_llm(provider, config)
    except (ProviderNotConfigured, CredentialDecryptionError, UnsupportedLLMProvider):
        return None
    try:
        try:
            models = await list_models_cached(redis, llm, config)
        finally:
            await llm.aclose()
    except Exception:  # a provider outage must not break the estimate
        return None
    for info in models:
        if info.id == model and info.prompt_price_per_million is not None:
            return info.prompt_price_per_million, info.completion_price_per_million or Decimal(0)
    return None
