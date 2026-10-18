"""The public podcast feed of a show: RSS 2.0 with the iTunes and Podcasting 2.0 namespaces.

Only published episodes are listed. Their GUIDs are the episode ids, which never change, so apps
do not show an episode twice when the site is moved or its URL changes.
"""

import hashlib
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from datetime import UTC, datetime
from email.utils import format_datetime
from urllib.parse import urlsplit

from byop.models import Episode, Show

ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ATOM = "http://www.w3.org/2005/Atom"
PODCAST = "https://podcastindex.org/namespace/1.0"
# Fixed namespace id of the Podcasting 2.0 `podcast:guid` (a UUIDv5 of the feed address).
PODCAST_GUID_NAMESPACE = uuid.UUID("ead4c236-bf58-58c6-a2c6-a6b28d128cb6")

DEFAULT_CATEGORY = "News"
GENERATOR = "BYOP"

for prefix, uri in (("itunes", ITUNES), ("atom", ATOM), ("podcast", PODCAST)):
    ET.register_namespace(prefix, uri)


def _base(base_url: str) -> str:
    return base_url.rstrip("/")


def feed_url(base_url: str, slug: str) -> str:
    return f"{_base(base_url)}/feeds/{slug}.xml"


def media_url(base_url: str, episode_id: uuid.UUID) -> str:
    return f"{_base(base_url)}/media/episodes/{episode_id}.mp3"


def cover_url(base_url: str, show: Show) -> str | None:
    if not show.cover_key:
        return None
    return f"{_base(base_url)}/api/shows/{show.id}/cover?v={int(show.updated_at.timestamp())}"


def podcast_guid(url: str) -> uuid.UUID:
    """The spec derives it from the feed address without scheme and trailing slashes."""
    parts = urlsplit(url)
    return uuid.uuid5(PODCAST_GUID_NAMESPACE, f"{parts.netloc}{parts.path}".rstrip("/"))


def _text(parent: ET.Element, tag: str, text: str, **attrs: str) -> ET.Element:
    element = ET.SubElement(parent, tag, attrs)
    element.text = text
    return element


def _rfc822(moment: datetime) -> str:
    return format_datetime(moment.astimezone(UTC), usegmt=True)


def published_episodes(episodes: Sequence[Episode]) -> list[Episode]:
    """Newest first; an episode without audio or a publication time cannot be in a feed."""
    return sorted(
        (e for e in episodes if e.published_at is not None and e.audio_key and e.size_bytes),
        key=lambda e: (e.published_at or datetime.min.replace(tzinfo=UTC), str(e.id)),
        reverse=True,
    )


def build_feed(show: Show, episodes: Sequence[Episode], base_url: str) -> bytes:
    """The feed document for `show`; `episodes` may hold drafts, which are left out."""
    listed = published_episodes(episodes)
    url = feed_url(base_url, show.slug)
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")

    _text(channel, "title", show.title)
    _text(channel, "link", _base(base_url))
    _text(channel, "description", show.description.strip() or show.topic)
    _text(channel, "language", show.language)
    ET.SubElement(
        channel, f"{{{ATOM}}}link", {"href": url, "rel": "self", "type": "application/rss+xml"}
    )
    last = listed[0].published_at if listed else None
    _text(channel, "lastBuildDate", _rfc822(last or show.updated_at))
    _text(channel, "generator", GENERATOR)

    author = (show.feed_author or "").strip() or show.title
    _text(channel, f"{{{ITUNES}}}author", author)
    _text(channel, f"{{{ITUNES}}}summary", show.description.strip() or show.topic)
    _text(channel, f"{{{ITUNES}}}type", "episodic")
    _text(channel, f"{{{ITUNES}}}explicit", "true" if show.feed_explicit else "false")
    ET.SubElement(
        channel,
        f"{{{ITUNES}}}category",
        {"text": (show.feed_category or "").strip() or DEFAULT_CATEGORY},
    )
    if show.feed_email:
        owner = ET.SubElement(channel, f"{{{ITUNES}}}owner")
        _text(owner, f"{{{ITUNES}}}name", author)
        _text(owner, f"{{{ITUNES}}}email", show.feed_email)
    cover = cover_url(base_url, show)
    if cover:
        ET.SubElement(channel, f"{{{ITUNES}}}image", {"href": cover})
        image = ET.SubElement(channel, "image")
        _text(image, "url", cover)
        _text(image, "title", show.title)
        _text(image, "link", _base(base_url))
    _text(channel, f"{{{PODCAST}}}guid", str(podcast_guid(url)))

    # Episode numbers follow publication order, so a published episode keeps its number.
    items: list[ET.Element] = []
    for number, episode in enumerate(reversed(listed), start=1):
        assert episode.published_at is not None and episode.size_bytes is not None
        item = ET.Element("item")
        _text(item, "title", episode.title)
        _text(item, "link", _base(base_url))
        _text(item, "description", episode.description.strip() or episode.title)
        _text(item, "guid", str(episode.id), isPermaLink="false")
        _text(item, "pubDate", _rfc822(episode.published_at))
        ET.SubElement(
            item,
            "enclosure",
            {
                "url": media_url(base_url, episode.id),
                "length": str(episode.size_bytes),
                "type": "audio/mpeg",
            },
        )
        if episode.duration_s is not None:
            _text(item, f"{{{ITUNES}}}duration", str(episode.duration_s))
        _text(item, f"{{{ITUNES}}}explicit", "true" if show.feed_explicit else "false")
        _text(item, f"{{{ITUNES}}}episode", str(number))
        _text(item, f"{{{ITUNES}}}episodeType", "full")
        items.append(item)
    channel.extend(reversed(items))  # newest first

    ET.indent(rss)
    document: bytes = ET.tostring(rss, encoding="utf-8", xml_declaration=True)
    return document


def etag_of(body: bytes) -> str:
    return f'"{hashlib.sha256(body).hexdigest()[:32]}"'
