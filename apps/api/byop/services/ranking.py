"""Choosing the stories for an episode: rank, merge coverage of the same event, and reserve."""

import uuid
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings
from byop.models import Item, Show
from byop.models.enums import ShowStyle
from byop.providers.llm import (
    CallMetadata,
    LLMError,
    Message,
    UnsupportedLLMProvider,
    get_llm,
)
from byop.services.credentials import (
    CredentialDecryptionError,
    CredentialResolver,
    ProviderNotConfigured,
)
from byop.services.llm_choice import show_model

log = structlog.get_logger(__name__)

STAGE = "ranking"
CANDIDATE_LIMIT = 60  # how many of the newest items the model is shown
MAX_RESERVE_ATTEMPTS = 3
SUMMARY_CHARS = 300
REASON_CHARS = 300

STYLE_BRIEFS: dict[ShowStyle, str] = {
    ShowStyle.NEWS_BRIEFING: "a tight briefing on the most important news",
    ShowStyle.CONVERSATIONAL: "a relaxed conversation about what is going on",
    ShowStyle.DEEP_DIVE: "an in-depth look at a few stories",
    ShowStyle.INTERVIEW: "an interview-style discussion built around the stories",
}


class _Pick(BaseModel):
    item: int  # the number the item had in the prompt
    score: float = 5.0
    reason: str = ""
    supporting: list[int] = Field(default_factory=list)


class _Ranking(BaseModel):
    selections: list[_Pick] = Field(default_factory=list, max_length=60)


@dataclass(frozen=True)
class RankedItem:
    item_id: uuid.UUID
    score: float  # 0-10, higher is better; 0 for the recency fallback
    reason: str
    # Other items about the same event, attached as supporting sources.
    supporting_item_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class RankedSelection:
    items: list[RankedItem]
    # Each group is the chosen item followed by the items merged into it (only groups of 2+).
    merged_groups: list[list[uuid.UUID]] = field(default_factory=list)
    used_fallback: bool = False
    fallback_reason: str | None = None
    candidates: int = 0

    @property
    def reserved_ids(self) -> list[uuid.UUID]:
        return [i for pick in self.items for i in (pick.item_id, *pick.supporting_item_ids)]


def _when(item: Item) -> float:
    stamp = item.published_at or item.ingested_at
    return stamp.timestamp()


def _newest_first(items: list[Item]) -> list[Item]:
    return sorted(items, key=_when, reverse=True)


def _describe(position: int, item: Item) -> str:
    when = (item.published_at or item.ingested_at).date().isoformat()
    host = urlsplit(item.canonical_url).netloc
    summary = " ".join(item.summary.split())[:SUMMARY_CHARS]
    return f"[{position}] ({when}, {host}) {item.title}" + (f" — {summary}" if summary else "")


def build_messages(show: Show, listed: list[Item], limit: int) -> list[Message]:
    hints = (
        "\nThe host's priorities, which matter more than anything else here:\n"
        f"{show.ranking_hints}\n"
        if show.ranking_hints and show.ranking_hints.strip()
        else ""
    )
    numbered = "\n".join(_describe(n, item) for n, item in enumerate(listed, start=1))
    system = (
        "You are the editor of a podcast. You choose which stories go into the next episode: "
        "the most newsworthy and relevant, with variety, and never the same event twice."
    )
    user = f"""Podcast topic: {show.topic}
Format: {STYLE_BRIEFS[show.style]}. Language: {show.language}.{hints}
Choose the {limit} best stories from the list below (fewer if there are not that many worth
telling). Several items may cover the same event: pick the most informative one as the main
item and list the others under "supporting" so they are used as extra sources instead of
becoming separate stories.

Return JSON {{"selections": [{{"item": <number>, "score": <0-10>, "reason": "<one sentence>",
"supporting": [<numbers>]}}]}}, best first. Use each number at most once overall.

Items:
{numbered}"""
    return [Message("system", system), Message("user", user)]


def _by_recency(candidates: list[Item], limit: int, reason: str, total: int) -> RankedSelection:
    picks = [
        RankedItem(item.id, 0.0, "Most recent item (the ranking model was not available)")
        for item in _newest_first(candidates)[:limit]
    ]
    return RankedSelection(picks, [], used_fallback=True, fallback_reason=reason, candidates=total)


def _clean(picks: list[_Pick], listed: list[Item], limit: int) -> list[RankedItem]:
    """Keep valid picks only: real items, each used once, at most `limit` stories."""
    used: set[int] = set()
    result: list[RankedItem] = []
    for pick in picks:
        if len(result) >= limit:
            break
        if not 1 <= pick.item <= len(listed) or pick.item in used:
            continue
        used.add(pick.item)
        supporting: list[uuid.UUID] = []
        for other in pick.supporting:
            if 1 <= other <= len(listed) and other not in used:
                used.add(other)
                supporting.append(listed[other - 1].id)
        result.append(
            RankedItem(
                item_id=listed[pick.item - 1].id,
                score=round(min(10.0, max(0.0, pick.score)), 1),
                reason=(pick.reason.strip() or "Chosen by the editor model.")[:REASON_CHARS],
                supporting_item_ids=tuple(supporting),
            )
        )
    return sorted(result, key=lambda r: r.score, reverse=True)  # stable: ties keep model order


async def rank_items(
    resolver: CredentialResolver,
    settings: Settings,
    show: Show,
    items: list[Item],
    *,
    limit: int | None = None,
    run_id: uuid.UUID | None = None,
) -> RankedSelection:
    """The best `limit` (default: the show's items per episode) of `items`, with duplicates merged.

    Uses the show's language model. If that fails or answers nonsense, the most recent items are
    taken instead and the selection says so (`used_fallback`), so a run never stops here.
    """
    limit = limit or show.items_per_episode
    total = len(items)
    listed = _newest_first(items)[:CANDIDATE_LIMIT]
    if not listed:
        return RankedSelection([], candidates=0)

    def fallback(reason: str) -> RankedSelection:
        log.warning(
            "ranking_fallback",
            show_id=str(show.id),
            run_id=str(run_id) if run_id else None,
            reason=reason,
        )
        return _by_recency(listed, limit, reason, total)

    chosen = show_model(settings, show)
    if chosen is None:
        return fallback("No language model is set up for this show")
    provider, model = chosen
    try:
        config = await resolver.get(show.user_id, provider)
        llm = get_llm(provider, config)
    except (ProviderNotConfigured, CredentialDecryptionError, UnsupportedLLMProvider) as exc:
        return fallback(f"The {provider.value} provider is not set up: {exc}")

    try:
        result = await llm.complete(
            build_messages(show, listed, limit),
            model=model,
            response_schema=_Ranking,
            temperature=0.2,
            metadata=CallMetadata(show_id=show.id, run_id=run_id, stage=STAGE),
        )
    except LLMError as exc:
        return fallback(f"The language model failed: {exc}")
    finally:
        await llm.aclose()
    assert isinstance(result.parsed, _Ranking)

    picks = _clean(result.parsed.selections, listed, limit)
    if not picks:
        return fallback("The language model returned no usable selection")
    groups = [[p.item_id, *p.supporting_item_ids] for p in picks if p.supporting_item_ids]
    return RankedSelection(picks, groups, candidates=total)


# --- candidates and reservation -------------------------------------------------------------


def _available(show: Show, run_id: uuid.UUID | None) -> list[object]:
    """Items nobody has used or is currently holding (this run's own holds still count)."""
    held: ColumnElement[bool] = Item.reserved_run_id.is_(None)
    if run_id is not None:
        held = or_(held, Item.reserved_run_id == run_id)
    return [
        Item.show_id == show.id,
        Item.user_id == show.user_id,
        Item.used_in_episode_id.is_(None),
        held,
    ]


async def available_items(
    session: AsyncSession, show: Show, run_id: uuid.UUID | None = None
) -> list[Item]:
    rows = await session.scalars(
        select(Item)
        .where(*_available(show, run_id))  # type: ignore[arg-type]
        .order_by(Item.published_at.desc().nulls_last(), Item.ingested_at.desc())
        .limit(CANDIDATE_LIMIT)
    )
    return list(rows)


async def reserve_items(
    session: AsyncSession, show: Show, run_id: uuid.UUID, item_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Hold `item_ids` for `run_id`; returns the ones that are now held by it.

    One statement: rows locked or taken by a concurrent run are skipped (`SKIP LOCKED`), so
    two runs can never hold the same item. Reserving what the run already holds is a no-op.
    """
    if not item_ids:
        return set()
    free = (
        select(Item.id)
        .where(Item.id.in_(item_ids), *_available(show, run_id))  # type: ignore[arg-type]
        .with_for_update(skip_locked=True)
    )
    rows = await session.execute(
        update(Item).where(Item.id.in_(free)).values(reserved_run_id=run_id).returning(Item.id)
    )
    reserved = {row[0] for row in rows}
    await session.commit()
    return reserved


async def release_items(session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> int:
    """Give back everything `run_id` holds (the run failed, or its draft was rejected)."""
    rows = await session.execute(
        update(Item)
        .where(Item.reserved_run_id == run_id, Item.user_id == user_id)
        .values(reserved_run_id=None)
        .returning(Item.id)
    )
    count = len(rows.all())
    await session.commit()
    return count


async def commit_items(
    session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID, episode_id: uuid.UUID
) -> int:
    """The run produced an episode: its held items are now used by it, for good."""
    rows = await session.execute(
        update(Item)
        .where(Item.reserved_run_id == run_id, Item.user_id == user_id)
        .values(used_in_episode_id=episode_id, reserved_run_id=None)
        .returning(Item.id)
    )
    count = len(rows.all())
    await session.commit()
    return count


async def select_for_run(
    session: AsyncSession,
    resolver: CredentialResolver,
    settings: Settings,
    show: Show,
    run_id: uuid.UUID,
) -> RankedSelection:
    """Rank the show's available items and reserve the chosen ones for `run_id`.

    If a concurrent run takes some of them in between, the partial hold is released and the
    ranking is redone on what is left. After `MAX_RESERVE_ATTEMPTS` the newest items that can
    still be reserved are taken instead.
    """
    for _ in range(MAX_RESERVE_ATTEMPTS):
        candidates = await available_items(session, show, run_id)
        selection = await rank_items(resolver, settings, show, candidates, run_id=run_id)
        if not selection.items:
            return selection
        held = await reserve_items(session, show, run_id, selection.reserved_ids)
        if all(pick.item_id in held for pick in selection.items):
            # Supporting items another run grabbed are simply not attached.
            picks = [
                RankedItem(
                    p.item_id,
                    p.score,
                    p.reason,
                    tuple(i for i in p.supporting_item_ids if i in held),
                )
                for p in selection.items
            ]
            groups = [[p.item_id, *p.supporting_item_ids] for p in picks if p.supporting_item_ids]
            return RankedSelection(
                picks,
                groups,
                selection.used_fallback,
                selection.fallback_reason,
                selection.candidates,
            )
        await release_items(session, show.user_id, run_id)

    reason = "Items kept being taken by another run"
    log.warning("ranking_fallback", show_id=str(show.id), run_id=str(run_id), reason=reason)
    picks = []
    for item in await available_items(session, show, run_id):
        if len(picks) >= show.items_per_episode:
            break
        if await reserve_items(session, show, run_id, [item.id]):
            picks.append(RankedItem(item.id, 0.0, "Most recent item still available"))
    return RankedSelection(picks, [], used_fallback=True, fallback_reason=reason)
