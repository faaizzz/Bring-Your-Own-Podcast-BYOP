from dataclasses import dataclass
from datetime import datetime

import anyio.to_thread
import feedparser

from byop.services.ingest.dates import from_struct, parse_date
from byop.services.ingest.extract import MAX_SUMMARY_CHARS, strip_html
from byop.services.safe_http import FetchError, fetch_bytes

PREVIEW_TITLES = 3
MAX_TITLE_LENGTH = 200
FEED_ACCEPT = (
    "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5"
)


class FeedInvalid(Exception):
    """The URL does not serve a usable RSS/Atom feed; the message says why."""


@dataclass(frozen=True)
class FeedPreview:
    title: str | None
    entry_count: int
    latest_titles: list[str]
    # Publication time of the newest entry that has one; None when no entry is dated.
    newest: datetime | None = None


def _looks_like_html(content: bytes, content_type: str | None) -> bool:
    if content_type and "html" in content_type.lower():
        return True
    return content.lstrip()[:15].lower().startswith((b"<!doctype html", b"<html"))


def _entry_time(entry: feedparser.FeedParserDict) -> datetime | None:
    return from_struct(entry.get("published_parsed") or entry.get("updated_parsed"))


def parse_feed(content: bytes, content_type: str | None = None) -> FeedPreview:
    """Read RSS, Atom or RDF `content` (CPU-bound; call from a thread for large feeds)."""
    parsed = feedparser.parse(content)
    # `version` is empty unless a real feed format was recognised, even when the parser salvaged
    # something (it reads the <title> of an HTML page, for instance).
    _reject_non_feed(parsed, content, content_type)
    feed_title = str(parsed.feed.get("title", "")).strip()
    if not parsed.entries and not feed_title:
        raise FeedInvalid("The feed has no title and no entries; it may be empty or damaged")
    titles = [
        str(entry.title).strip()[:MAX_TITLE_LENGTH]
        for entry in parsed.entries
        if str(entry.get("title", "")).strip()
    ]
    times = [t for t in (_entry_time(entry) for entry in parsed.entries) if t is not None]
    return FeedPreview(
        title=feed_title[:MAX_TITLE_LENGTH] or None,
        entry_count=len(parsed.entries),
        latest_titles=titles[:PREVIEW_TITLES],
        newest=max(times) if times else None,
    )


async def preview_feed(url: str, *, allow_private: bool = False) -> FeedPreview:
    """Fetch `url` and describe the feed it serves; raises `FeedInvalid` with the reason."""
    try:
        fetched = await fetch_bytes(url, allow_private=allow_private, accept=FEED_ACCEPT)
    except FetchError as exc:
        raise FeedInvalid(str(exc)) from exc
    return await anyio.to_thread.run_sync(parse_feed, fetched.content, fetched.content_type)


@dataclass(frozen=True)
class FeedEntry:
    title: str
    link: str
    summary: str
    published: datetime | None


def _reject_non_feed(
    parsed: feedparser.FeedParserDict, content: bytes, content_type: str | None
) -> None:
    if not parsed.get("version"):  # the key is absent altogether for empty input
        if _looks_like_html(content, content_type):
            raise FeedInvalid("The URL returns a web page, not an RSS or Atom feed")
        raise FeedInvalid("The response is not a valid RSS or Atom feed")


def parse_entries(content: bytes, content_type: str | None = None) -> list[FeedEntry]:
    """The entries of a feed, as the feed lists them. Entries without a link or title are
    skipped; dates come from the feed's own fields (RFC 822 or ISO 8601), in UTC.
    Raises `FeedInvalid` when `content` is not a feed at all (an empty feed is fine)."""
    parsed = feedparser.parse(content)
    _reject_non_feed(parsed, content, content_type)
    entries: list[FeedEntry] = []
    for entry in parsed.entries:
        link = str(entry.get("link") or "").strip()
        title = str(entry.get("title") or "").strip()
        if not link or not title:
            continue
        body = str(entry.get("summary") or "")
        if not body and entry.get("content"):
            body = str(entry.content[0].get("value", ""))
        published = _entry_time(entry) or parse_date(
            str(entry.get("published") or entry.get("updated") or "")
        )
        entries.append(
            FeedEntry(
                title=title,
                link=link,
                summary=strip_html(body)[:MAX_SUMMARY_CHARS],
                published=published,
            )
        )
    return entries
