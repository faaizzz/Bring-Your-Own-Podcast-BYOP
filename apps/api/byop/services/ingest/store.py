"""Deduplicate collected items against what the show already has, then save the new ones.

Every comparison with existing rows is one SQL statement for the whole batch (the trigram
index does the fuzzy matching), so the cost does not grow with a loop over the items.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Item
from byop.services.ingest.collect import RawItem

INSERT_BATCH = 500


@dataclass(frozen=True)
class Candidate:
    """An item that passed the cheap filters and is ready to be compared and saved."""

    raw: RawItem
    canonical_url: str
    content_hash: str
    language: str | None


@dataclass
class StoreResult:
    inserted: int = 0
    updated: int = 0
    same_url: int = 0
    same_content: int = 0
    similar_title: int = 0

    @property
    def duplicates(self) -> int:
        return self.same_url + self.same_content + self.similar_title


_FUZZY_VS_EXISTING = text(
    """
    SELECT t.ord FROM unnest(CAST(:titles AS text[])) WITH ORDINALITY AS t(title, ord)
    WHERE EXISTS (
        SELECT 1 FROM items i
        WHERE i.show_id = :show_id AND i.user_id = :user_id
          AND i.ingested_at >= :since AND i.title % t.title
    )
    """
)

_FUZZY_WITHIN_BATCH = text(
    """
    SELECT a.ord FROM unnest(CAST(:titles AS text[])) WITH ORDINALITY AS a(title, ord)
    WHERE EXISTS (
        SELECT 1 FROM unnest(CAST(:titles AS text[])) WITH ORDINALITY AS b(title, ord)
        WHERE b.ord < a.ord AND b.title % a.title
    )
    """
)


async def _similar(
    session: AsyncSession,
    statement: object,
    titles: list[str],
    params: dict[str, object],
) -> set[int]:
    """1-based positions in `titles` that match the statement's similarity rule."""
    rows = await session.execute(statement, {"titles": titles, **params})  # type: ignore[call-overload]
    return {int(row[0]) for row in rows}


async def store_items(
    session: AsyncSession,
    show_id: uuid.UUID,
    user_id: uuid.UUID,
    candidates: list[Candidate],
    *,
    similarity: float,
    window_days: int,
    now: datetime,
) -> StoreResult:
    result = StoreResult()
    if not candidates:
        return result

    # 1. The same URL or the same text twice in this batch: keep the first.
    seen_urls: set[str] = set()
    seen_hashes: set[str] = set()
    batch: list[Candidate] = []
    for candidate in candidates:
        if candidate.canonical_url in seen_urls:
            result.same_url += 1
        elif candidate.content_hash in seen_hashes:
            result.same_content += 1
        else:
            seen_urls.add(candidate.canonical_url)
            seen_hashes.add(candidate.content_hash)
            batch.append(candidate)

    # 2. Exact matches with what the show already has.
    found = await session.execute(
        select(Item.canonical_url, Item.content_hash).where(
            Item.show_id == show_id,
            Item.user_id == user_id,
            or_(
                Item.canonical_url.in_([c.canonical_url for c in batch]),
                Item.content_hash.in_([c.content_hash for c in batch]),
            ),
        )
    )
    known = found.all()
    url_hash = {url: chash for url, chash in known}
    hashes = {chash for _, chash in known}
    fresh: list[Candidate] = []
    changed: list[Candidate] = []
    for candidate in batch:
        existing_hash = url_hash.get(candidate.canonical_url)
        if existing_hash is not None:
            if candidate.raw.watch and existing_hash != candidate.content_hash:
                changed.append(candidate)  # a watched page whose text moved on
            else:
                result.same_url += 1
        elif candidate.content_hash in hashes:
            result.same_content += 1
        else:
            fresh.append(candidate)

    # 3. Near-identical headlines, against recent items and within the batch: two statements.
    if fresh:
        titles = [c.raw.title for c in fresh]
        await session.execute(
            text("SELECT set_config('pg_trgm.similarity_threshold', :value, true)"),
            {"value": str(similarity)},
        )
        skip = await _similar(
            session,
            _FUZZY_VS_EXISTING,
            titles,
            {"show_id": show_id, "user_id": user_id, "since": now - timedelta(days=window_days)},
        )
        skip |= await _similar(session, _FUZZY_WITHIN_BATCH, titles, {})
        result.similar_title = len(skip)
        fresh = [c for position, c in enumerate(fresh, start=1) if position not in skip]

    # 4. Save.
    for start in range(0, len(fresh), INSERT_BATCH):
        chunk = fresh[start : start + INSERT_BATCH]
        rows = [
            {
                "id": uuid.uuid4(),
                "user_id": user_id,
                "show_id": show_id,
                "source_id": c.raw.source_id,
                "canonical_url": c.canonical_url,
                "content_hash": c.content_hash,
                "title": c.raw.title,
                "summary": c.raw.summary,
                "published_at": c.raw.published_at,
                "language": c.language,
                "ingested_at": now,
            }
            for c in chunk
        ]
        inserted = await session.execute(
            pg_insert(Item)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["show_id", "canonical_url"])
            .returning(Item.id)
        )
        result.inserted += len(inserted.all())
    for candidate in changed:
        await session.execute(
            update(Item)
            .where(
                Item.show_id == show_id,
                Item.user_id == user_id,
                Item.canonical_url == candidate.canonical_url,
            )
            .values(
                title=candidate.raw.title,
                summary=candidate.raw.summary,
                content_hash=candidate.content_hash,
                published_at=None,
                ingested_at=now,
                updated_at=func.now(),
                used_in_episode_id=None,  # new text: worth covering again
            )
        )
        result.updated += 1
    await session.commit()
    return result
