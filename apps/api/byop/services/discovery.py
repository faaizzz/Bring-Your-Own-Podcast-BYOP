import asyncio
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings
from byop.models import Source
from byop.models.enums import CredentialProvider, SourceKind
from byop.providers.llm import CallMetadata, Message, UnsupportedLLMProvider, get_llm
from byop.schemas.discovery import DiscoveredSource, RawCandidate, RawCandidates
from byop.services.credentials import (
    CredentialDecryptionError,
    CredentialResolver,
    ProviderNotConfigured,
)
from byop.services.feeds import FeedInvalid, preview_feed
from byop.services.safe_http import FetchError, fetch_bytes

log = structlog.get_logger(__name__)

STAGE = "discovery"
RECENT_DAYS = 90  # a feed whose newest item is older than this is considered dead
MAX_CANDIDATES_TO_CHECK = 14
MAX_SEARCH_QUERIES = 3
CHECK_CONCURRENCY = 5
ONLINE_SUFFIX = ":online"


class DiscoveryUnavailable(Exception):
    """Discovery cannot run (no model configured, ...); the message tells the user what to do."""


@dataclass(frozen=True)
class DiscoveryRequest:
    user_id: uuid.UUID
    show_id: uuid.UUID | None
    topic: str
    language: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None


def search_model_id(provider: CredentialProvider, model: str) -> str:
    """On OpenRouter a model can search the web when its id ends in `:online`.

    Models that search natively (Perplexity's) and ids already suffixed are left alone.
    """
    if provider is CredentialProvider.OPENROUTER and not (
        model.endswith(ONLINE_SUFFIX) or model.startswith("perplexity/")
    ):
        return f"{model}{ONLINE_SUFFIX}"
    return model


def pick_model(settings: Settings, request: DiscoveryRequest) -> tuple[CredentialProvider, str]:
    """The discovery model, then the show's, then the instance default."""
    choices = (
        (settings.discovery_llm_provider, settings.discovery_llm_model),
        (request.llm_provider, request.llm_model),
        (settings.default_llm_provider, settings.default_llm_model),
    )
    for provider, model in choices:
        if provider and model:
            return CredentialProvider(provider), model
    raise DiscoveryUnavailable(
        "No language model is set up for discovery. Choose one for the show, or set "
        "DEFAULT_LLM_PROVIDER and DEFAULT_LLM_MODEL (or DISCOVERY_LLM_*) in .env."
    )


def build_messages(request: DiscoveryRequest) -> list[Message]:
    language = request.language or "en"
    system = (
        "You are a research assistant who finds reliable, current sources for a podcast. "
        "Search the web, and only propose sources you actually found: never invent a URL."
    )
    user = f"""Podcast topic: {request.topic}
Preferred language: {language} (include English-language sources only if few exist).

Propose sources of three kinds and return them as JSON `{{"candidates": [...]}}`:
- "rss": direct URLs of RSS or Atom feeds (not the website's home page) that publish new
  items regularly. Up to 8.
- "url": pages worth watching for news on the topic (a project's blog or releases page, a news
  section). Up to 3.
- "web_search": 1 to 3 short search queries that would surface fresh news about the topic.
  Put the query text in "value".

Each candidate has "kind", "name" (a short title), "value" (the feed or page URL, or the query)
and "reason" (one sentence on why it fits the topic). Prefer sources that are active, well
regarded and specific to the topic."""
    return [Message("system", system), Message("user", user)]


def _normal(kind: str, value: str) -> tuple[str, str]:
    text = value.strip()
    if kind == "web_search":
        return kind, " ".join(text.lower().split())
    parts = urlsplit(text)
    return kind, f"{parts.netloc.lower()}{parts.path.rstrip('/')}?{parts.query}"


def _clean(raw: list[RawCandidate]) -> list[RawCandidate]:
    """Known kinds only, no empties, no duplicates."""
    kinds = {k.value for k in SourceKind}
    seen: set[tuple[str, str]] = set()
    result: list[RawCandidate] = []
    for candidate in raw:
        kind = candidate.kind.strip().lower()
        value = candidate.value.strip()
        if kind not in kinds or not value:
            continue
        key = _normal(kind, value)
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate.model_copy(update={"kind": kind, "value": value}))
    return result


async def _check(
    candidate: RawCandidate, *, allow_private: bool, now: datetime
) -> DiscoveredSource | None:
    """Keep a feed only if it parses and is alive, a page only if it can be fetched."""
    reason = candidate.reason.strip()[:500]
    try:
        if candidate.kind == SourceKind.RSS:
            preview = await preview_feed(candidate.value, allow_private=allow_private)
            if preview.entry_count == 0:
                return None
            if preview.newest and now - preview.newest > timedelta(days=RECENT_DAYS):
                return None
            return DiscoveredSource(
                kind=SourceKind.RSS,
                name=(candidate.name.strip() or preview.title or candidate.value)[:200],
                value=candidate.value,
                reason=reason,
                recent_titles=preview.latest_titles,
            )
        await fetch_bytes(candidate.value, allow_private=allow_private, max_bytes=1024 * 1024)
    except (FeedInvalid, FetchError):
        return None
    return DiscoveredSource(
        kind=SourceKind.URL,
        name=(candidate.name.strip() or urlsplit(candidate.value).netloc)[:200],
        value=candidate.value,
        reason=reason,
    )


def _baseline_queries(topic: str) -> list[RawCandidate]:
    short = re.sub(r"\s+", " ", topic).strip()[:150]
    return [
        RawCandidate(
            kind="web_search",
            value=f"{short} latest news",
            name="Latest news",
            reason="A general search for new stories on the topic.",
        ),
        RawCandidate(
            kind="web_search",
            value=f"{short} announcements and releases",
            name="Announcements",
            reason="Looks for launches and official announcements.",
        ),
    ]


async def discover_sources(
    session: AsyncSession,
    resolver: CredentialResolver,
    settings: Settings,
    request: DiscoveryRequest,
) -> list[DiscoveredSource]:
    """Ask a web-searching model for sources, keep the ones that check out, and add baseline
    search queries. Sources the show already has are left out."""
    provider, model = pick_model(settings, request)
    try:
        config = await resolver.get(request.user_id, provider)
        llm = get_llm(provider, config)
    except (ProviderNotConfigured, CredentialDecryptionError, UnsupportedLLMProvider) as exc:
        raise DiscoveryUnavailable(
            f"The {provider.value} provider is not set up: {exc}. Configure it under "
            "Settings › Integrations."
        ) from exc

    try:
        result = await llm.complete(
            build_messages(request),
            model=search_model_id(provider, model),
            response_schema=RawCandidates,
            temperature=0.2,
            # Attributes the cost of this call to the show (usage capture reads the same fields).
            metadata=CallMetadata(show_id=request.show_id, stage=STAGE),
        )
    finally:
        await llm.aclose()
    assert isinstance(result.parsed, RawCandidates)

    taken: set[tuple[str, str]] = set()
    if request.show_id is not None:
        rows = await session.execute(
            select(Source.kind, Source.value).where(
                Source.show_id == request.show_id, Source.user_id == request.user_id
            )
        )
        taken = {_normal(kind.value, value) for kind, value in rows.all()}

    cleaned = [c for c in _clean(result.parsed.candidates) if _normal(c.kind, c.value) not in taken]
    to_check = [c for c in cleaned if c.kind != SourceKind.WEB_SEARCH][:MAX_CANDIDATES_TO_CHECK]
    queries = [c for c in cleaned if c.kind == SourceKind.WEB_SEARCH][:MAX_SEARCH_QUERIES]
    if not queries:
        queries = [
            c for c in _baseline_queries(request.topic) if _normal(c.kind, c.value) not in taken
        ][:MAX_SEARCH_QUERIES]

    gate = asyncio.Semaphore(CHECK_CONCURRENCY)
    now = datetime.now(UTC)

    async def check(candidate: RawCandidate) -> DiscoveredSource | None:
        async with gate:
            return await _check(
                candidate, allow_private=settings.sources_allow_private_networks, now=now
            )

    checked = await asyncio.gather(*(check(c) for c in to_check))
    kept = [c for c in checked if c is not None]
    log.info(
        "discovery_done",
        show_id=str(request.show_id) if request.show_id else None,
        proposed=len(cleaned),
        kept=len(kept),
        queries=len(queries),
    )
    feeds = [c for c in kept if c.kind is SourceKind.RSS]
    pages = [c for c in kept if c.kind is SourceKind.URL]
    searches = [
        DiscoveredSource(
            kind=SourceKind.WEB_SEARCH,
            name=(q.name.strip() or q.value)[:200],
            value=q.value,
            reason=q.reason.strip()[:500],
        )
        for q in queries
    ]
    return [*feeds, *pages, *searches]
