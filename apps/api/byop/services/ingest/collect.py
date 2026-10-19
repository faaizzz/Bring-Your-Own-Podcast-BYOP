"""Fetching raw items from one source. Each function raises `SourceFailed` with a reason."""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

import anyio.to_thread
import structlog
from pydantic import BaseModel, Field

from byop.models import Source
from byop.models.enums import SourceKind
from byop.providers.llm import CallMetadata, LLMError, Message, get_llm
from byop.services.credentials import ProviderConfig
from byop.services.discovery import search_model_id
from byop.services.feeds import FEED_ACCEPT, FeedInvalid, parse_entries
from byop.services.ingest.dates import parse_date
from byop.services.ingest.extract import MAX_SUMMARY_CHARS, decode, extract_page, strip_html
from byop.services.provider_ref import ProviderRef
from byop.services.safe_http import FetchError, fetch_bytes

log = structlog.get_logger(__name__)

STAGE = "ingest"
MAX_ITEMS_PER_SOURCE = 60
MAX_TITLE_CHARS = 500


class SourceFailed(Exception):
    """The source could not be read; the message ends up in `Source.last_error`."""


@dataclass(frozen=True)
class RawItem:
    source_id: uuid.UUID
    kind: SourceKind
    title: str
    url: str
    summary: str
    published_at: datetime | None
    # A watched page is one item that is replaced when its text changes. `fingerprint` then
    # covers the whole text, not just the summary.
    watch: bool = False
    fingerprint: str | None = None


async def collect_rss(source: Source, *, allow_private: bool) -> list[RawItem]:
    try:
        fetched = await fetch_bytes(source.value, allow_private=allow_private, accept=FEED_ACCEPT)
    except FetchError as exc:
        raise SourceFailed(str(exc)) from exc
    try:
        entries = await anyio.to_thread.run_sync(
            parse_entries, fetched.content, fetched.content_type
        )
    except FeedInvalid as exc:
        raise SourceFailed(str(exc)) from exc
    return [
        RawItem(
            source_id=source.id,
            kind=SourceKind.RSS,
            title=entry.title[:MAX_TITLE_CHARS],
            url=entry.link,
            summary=entry.summary,
            published_at=entry.published,
        )
        for entry in entries[:MAX_ITEMS_PER_SOURCE]
    ]


async def collect_page(source: Source, *, allow_private: bool) -> list[RawItem]:
    try:
        fetched = await fetch_bytes(
            source.value, allow_private=allow_private, accept="text/html,*/*;q=0.5"
        )
    except FetchError as exc:
        raise SourceFailed(str(exc)) from exc
    page = await anyio.to_thread.run_sync(
        extract_page, decode(fetched.content, fetched.content_type)
    )
    if page is None:
        raise SourceFailed("No readable text was found on the page")
    return [
        RawItem(
            source_id=source.id,
            kind=SourceKind.URL,
            title=(page.title or urlsplit(source.value).netloc)[:MAX_TITLE_CHARS],
            url=source.value,
            summary=page.text[:MAX_SUMMARY_CHARS],
            published_at=None,
            watch=True,
            fingerprint=hashlib.sha256(page.text.encode()).hexdigest(),
        )
    ]


class _SearchItem(BaseModel):
    title: str
    url: str
    summary: str = ""
    published_at: str | None = None


class _SearchItems(BaseModel):
    items: list[_SearchItem] = Field(default_factory=list, max_length=40)


@dataclass(frozen=True)
class SearchModel:
    """The web-searching model for `web_search` sources, resolved once per ingest."""

    provider: ProviderRef
    model: str
    config: ProviderConfig


async def collect_search(
    source: Source,
    *,
    search: SearchModel | None,
    topic: str,
    freshness_days: int,
    show_id: uuid.UUID,
    run_id: uuid.UUID | None,
) -> list[RawItem]:
    if search is None:
        raise SourceFailed("No language model is set up for web search sources")
    prompt = (
        f"Search the web for news from the last {freshness_days} days about: {source.value}\n"
        f"The podcast's topic is: {topic}\n\n"
        'Return JSON {"items": [...]} with up to 10 distinct items you actually found. Each item '
        'has "title", "url" (a direct link to the article), "summary" (two sentences) and '
        '"published_at" (ISO 8601 date or datetime, if known). Never invent a URL.'
    )
    llm = get_llm(search.config.provider, search.config)
    try:
        result = await llm.complete(
            [
                Message("system", "You find fresh, reliable news by searching the web."),
                Message("user", prompt),
            ],
            model=search_model_id(search.provider, search.model),
            response_schema=_SearchItems,
            temperature=0.2,
            metadata=CallMetadata(show_id=show_id, run_id=run_id, stage=STAGE),
        )
    except LLMError as exc:
        raise SourceFailed(f"The language model failed: {exc}") from exc
    finally:
        await llm.aclose()
    assert isinstance(result.parsed, _SearchItems)
    return [
        RawItem(
            source_id=source.id,
            kind=SourceKind.WEB_SEARCH,
            title=item.title.strip()[:MAX_TITLE_CHARS],
            url=item.url.strip(),
            summary=strip_html(item.summary)[:MAX_SUMMARY_CHARS],
            published_at=parse_date(item.published_at),
        )
        for item in result.parsed.items
        if item.title.strip() and item.url.strip()
    ]
