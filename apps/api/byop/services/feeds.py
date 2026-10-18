from dataclasses import dataclass

import anyio.to_thread
import feedparser

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


def _looks_like_html(content: bytes, content_type: str | None) -> bool:
    if content_type and "html" in content_type.lower():
        return True
    return content.lstrip()[:15].lower().startswith((b"<!doctype html", b"<html"))


def parse_feed(content: bytes, content_type: str | None = None) -> FeedPreview:
    """Read RSS, Atom or RDF `content` (CPU-bound; call from a thread for large feeds)."""
    parsed = feedparser.parse(content)
    # `version` is empty unless a real feed format was recognised, even when the parser salvaged
    # something (it reads the <title> of an HTML page, for instance).
    if not parsed.get("version"):  # the key is absent altogether for empty input
        if _looks_like_html(content, content_type):
            raise FeedInvalid("The URL returns a web page, not an RSS or Atom feed")
        raise FeedInvalid("The response is not a valid RSS or Atom feed")
    feed_title = str(parsed.feed.get("title", "")).strip()
    if not parsed.entries and not feed_title:
        raise FeedInvalid("The feed has no title and no entries; it may be empty or damaged")
    titles = [
        str(entry.title).strip()[:MAX_TITLE_LENGTH]
        for entry in parsed.entries
        if str(entry.get("title", "")).strip()
    ]
    return FeedPreview(
        title=feed_title[:MAX_TITLE_LENGTH] or None,
        entry_count=len(parsed.entries),
        latest_titles=titles[:PREVIEW_TITLES],
    )


async def preview_feed(url: str, *, allow_private: bool = False) -> FeedPreview:
    """Fetch `url` and describe the feed it serves; raises `FeedInvalid` with the reason."""
    try:
        fetched = await fetch_bytes(url, allow_private=allow_private, accept=FEED_ACCEPT)
    except FetchError as exc:
        raise FeedInvalid(str(exc)) from exc
    return await anyio.to_thread.run_sync(parse_feed, fetched.content, fetched.content_type)
