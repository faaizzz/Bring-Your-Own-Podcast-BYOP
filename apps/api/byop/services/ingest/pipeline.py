import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings
from byop.models import Run, Show, Source
from byop.models.enums import SourceKind
from byop.services.credentials import (
    CredentialDecryptionError,
    CredentialResolver,
    ProviderNotConfigured,
)
from byop.services.discovery import DiscoveryRequest, DiscoveryUnavailable, pick_model
from byop.services.ingest.canonical import canonical_url, content_hash
from byop.services.ingest.collect import (
    RawItem,
    SearchModel,
    SourceFailed,
    collect_page,
    collect_rss,
    collect_search,
)
from byop.services.ingest.language import detect_language, matches_language
from byop.services.ingest.store import Candidate, StoreResult, store_items

log = structlog.get_logger(__name__)

CONCURRENCY = 6
MAX_ERROR_CHARS = 500


class ShowMissing(Exception):
    pass


@dataclass
class SourceReport:
    source_id: uuid.UUID
    name: str
    fetched: int = 0
    error: str | None = None


@dataclass
class IngestResult:
    new_items: int = 0
    updated_items: int = 0
    fetched: int = 0
    invalid: int = 0
    stale: int = 0
    wrong_language: int = 0
    duplicates: int = 0
    sources: list[SourceReport] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "new_items": self.new_items,
            "updated_items": self.updated_items,
            "fetched": self.fetched,
            "invalid": self.invalid,
            "stale": self.stale,
            "wrong_language": self.wrong_language,
            "duplicates": self.duplicates,
            "sources": [
                {"id": str(s.source_id), "name": s.name, "fetched": s.fetched, "error": s.error}
                for s in self.sources
            ],
        }


async def _search_model(
    resolver: CredentialResolver, settings: Settings, show: Show
) -> SearchModel | None:
    """The model for `web_search` sources, or None when none is set up."""
    request = DiscoveryRequest(
        user_id=show.user_id,
        show_id=show.id,
        topic=show.topic,
        llm_provider=show.llm_provider,
        llm_model=show.llm_model,
    )
    try:
        provider, model = pick_model(settings, request)
        config = await resolver.get_ref(show.user_id, provider, "llm")
    except (DiscoveryUnavailable, ProviderNotConfigured, CredentialDecryptionError):
        return None
    return SearchModel(provider=provider, model=model, config=config)


async def set_run_progress(
    session: AsyncSession, run_id: uuid.UUID, user_id: uuid.UUID, stage: str, progress: int
) -> None:
    run = await session.scalar(select(Run).where(Run.id == run_id, Run.user_id == user_id))
    if run is not None:
        run.stage, run.progress = stage, progress
        await session.commit()


def _prepare(
    raw: list[RawItem], show: Show, *, oldest: datetime, result: IngestResult
) -> list[Candidate]:
    """Canonicalise, then drop what is invalid, too old or in the wrong language."""
    candidates: list[Candidate] = []
    for item in raw:
        url = canonical_url(item.url)
        if url is None or not item.title.strip():
            result.invalid += 1
            continue
        # A watched page has no date; everything else must be fresh (undated items pass).
        if item.published_at is not None and item.published_at < oldest:
            result.stale += 1
            continue
        language = detect_language(f"{item.title}. {item.summary}")
        if not matches_language(language, show.language):
            result.wrong_language += 1
            continue
        candidates.append(
            Candidate(
                raw=item,
                canonical_url=url,
                content_hash=item.fingerprint or content_hash(item.title, item.summary),
                language=language,
            )
        )
    return candidates


async def ingest_show(
    session: AsyncSession,
    resolver: CredentialResolver,
    settings: Settings,
    show_id: uuid.UUID,
    *,
    run_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> IngestResult:
    """Collect fresh, unique items for a show from all its enabled sources.

    One failing source records `last_error` and the rest carry on. Safe to repeat: items that
    were already collected are recognised and skipped.
    """
    now = now or datetime.now(UTC)
    # System context (a worker job): the owner comes from the show itself.
    show = await session.scalar(select(Show).where(Show.id == show_id))
    if show is None:
        raise ShowMissing(str(show_id))
    user_id = show.user_id
    if run_id is not None:
        await set_run_progress(session, run_id, user_id, "ingest", 5)

    sources = list(
        await session.scalars(
            select(Source)
            .where(Source.show_id == show_id, Source.user_id == user_id, Source.enabled.is_(True))
            .order_by(Source.created_at, Source.id)
        )
    )
    result = IngestResult()
    search = (
        await _search_model(resolver, settings, show)
        if any(s.kind is SourceKind.WEB_SEARCH for s in sources)
        else None
    )
    gate = asyncio.Semaphore(CONCURRENCY)

    async def collect(source: Source) -> list[RawItem] | SourceFailed:
        async with gate:
            try:
                async with asyncio.timeout(settings.ingest_source_timeout_s):
                    match source.kind:
                        case SourceKind.RSS:
                            return await collect_rss(
                                source, allow_private=settings.sources_allow_private_networks
                            )
                        case SourceKind.URL:
                            return await collect_page(
                                source, allow_private=settings.sources_allow_private_networks
                            )
                        case SourceKind.WEB_SEARCH:
                            return await collect_search(
                                source,
                                search=search,
                                topic=show.topic,
                                freshness_days=settings.ingest_freshness_days,
                                show_id=show.id,
                                run_id=run_id,
                            )
            except SourceFailed as exc:
                return exc
            except TimeoutError:
                return SourceFailed("The source took too long to answer")
            except Exception as exc:  # one broken source must not stop the others
                log.warning("ingest_source_crashed", source_id=str(source.id), exc_info=True)
                return SourceFailed(f"Unexpected error: {type(exc).__name__}")

    outcomes = await asyncio.gather(*(collect(s) for s in sources))

    raw: list[RawItem] = []
    for source, outcome in zip(sources, outcomes, strict=True):
        report = SourceReport(source_id=source.id, name=source.name or source.value)
        if isinstance(outcome, SourceFailed):
            report.error = str(outcome)[:MAX_ERROR_CHARS]
            source.last_error = report.error
        else:
            report.fetched = len(outcome)
            source.last_error = None
            source.last_fetched_at = now
            raw.extend(outcome)
        result.sources.append(report)
    result.fetched = len(raw)

    oldest = now - timedelta(days=settings.ingest_freshness_days)
    candidates = _prepare(raw, show, oldest=oldest, result=result)
    stored: StoreResult = await store_items(
        session,
        show_id,
        user_id,
        candidates,
        similarity=settings.ingest_title_similarity,
        window_days=settings.ingest_dedup_days,
        now=now,
    )
    await session.commit()  # the source status changes, if there was nothing to store
    result.new_items = stored.inserted
    result.updated_items = stored.updated
    result.duplicates = stored.duplicates
    if run_id is not None:
        await set_run_progress(session, run_id, user_id, "ingest", 20)
    log.info(
        "ingest_done",
        show_id=str(show_id),
        **{k: v for k, v in result.as_dict().items() if k != "sources"},
    )
    return result
