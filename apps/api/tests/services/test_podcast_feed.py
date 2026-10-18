import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from byop.models import Episode, Show
from byop.models.enums import EpisodeStatus
from byop.services.podcast_feed import (
    ITUNES,
    PODCAST,
    build_feed,
    feed_url,
    media_url,
    podcast_guid,
)

BASE = "https://pods.example.com/"
NS = {"itunes": ITUNES, "podcast": PODCAST, "atom": "http://www.w3.org/2005/Atom"}
T0 = datetime(2026, 5, 1, 7, 0, tzinfo=UTC)


def make_show(**values: object) -> Show:
    show = Show(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Daily AI",
        slug="daily-ai",
        topic="Artificial intelligence",
        description="What happened in AI today.",
        language="en",
        feed_explicit=False,
        feed_enabled=True,
        updated_at=T0,
        created_at=T0,
    )
    for name, value in values.items():
        setattr(show, name, value)
    return show


def make_episode(show: Show, n: int, **values: object) -> Episode:
    episode = Episode(
        id=uuid.UUID(int=n),
        user_id=show.user_id,
        show_id=show.id,
        title=f"Episode {n}",
        description=f"About {n}",
        status=EpisodeStatus.PUBLISHED,
        published_at=T0 + timedelta(days=n),
        audio_key=f"shows/{show.id}/episodes/{n}/audio.mp3",
        size_bytes=1_000_000 + n,
        duration_s=300 + n,
    )
    for name, value in values.items():
        setattr(episode, name, value)
    return episode


def parse(show: Show, episodes: list[Episode]) -> ET.Element:
    root = ET.fromstring(build_feed(show, episodes, BASE))
    channel = root.find("channel")
    assert channel is not None
    return channel


def test_the_document_is_rss_2_with_the_itunes_and_podcast_namespaces() -> None:
    show = make_show()
    body = build_feed(show, [make_episode(show, 1)], BASE)

    assert body.startswith(b"<?xml")
    root = ET.fromstring(body)
    assert root.tag == "rss" and root.attrib["version"] == "2.0"
    assert b'xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"' in body
    assert b'xmlns:podcast="https://podcastindex.org/namespace/1.0"' in body


def test_the_channel_has_what_podcast_directories_require() -> None:
    show = make_show(
        feed_author="Ada",
        feed_email="ada@example.com",
        feed_category="Technology",
        feed_explicit=True,
        cover_key="shows/x/cover.jpg",
    )
    channel = parse(show, [make_episode(show, 1)])

    def text(path: str) -> str | None:
        element = channel.find(path, NS)
        return None if element is None else element.text

    assert text("title") == "Daily AI"
    assert text("link") == "https://pods.example.com"
    assert text("description") == "What happened in AI today."
    assert text("language") == "en"
    assert text("itunes:author") == "Ada"
    assert text("itunes:explicit") == "true"
    assert text("itunes:type") == "episodic"
    category = channel.find("itunes:category", NS)
    assert category is not None and category.attrib["text"] == "Technology"
    assert text("itunes:owner/itunes:email") == "ada@example.com"
    self_link = channel.find("atom:link", NS)
    assert self_link is not None and self_link.attrib["rel"] == "self"
    assert self_link.attrib["href"] == "https://pods.example.com/feeds/daily-ai.xml"
    assert self_link.attrib["type"] == "application/rss+xml"
    cover = channel.find("itunes:image", NS)
    assert cover is not None
    assert cover.attrib["href"].startswith(f"https://pods.example.com/api/shows/{show.id}/cover?v=")
    assert text("podcast:guid") == str(podcast_guid("https://pods.example.com/feeds/daily-ai.xml"))
    assert parsedate_to_datetime(text("lastBuildDate") or "").year == 2026


def test_missing_optional_settings_get_sensible_defaults() -> None:
    show = make_show(description="", feed_author=None, feed_category=None, feed_email=None)
    channel = parse(show, [])

    assert channel.findtext("description") == "Artificial intelligence"  # the topic
    assert channel.findtext("itunes:author", namespaces=NS) == "Daily AI"
    category = channel.find("itunes:category", NS)
    assert category is not None and category.attrib["text"] == "News"
    assert channel.findtext("itunes:explicit", namespaces=NS) == "false"
    assert channel.find("itunes:owner", NS) is None
    assert channel.find("itunes:image", NS) is None  # no cover uploaded yet
    assert channel.findall("item") == []


def test_every_item_has_title_guid_pubdate_and_a_complete_enclosure() -> None:
    show = make_show()
    episode = make_episode(show, 3)
    (item,) = parse(show, [episode]).findall("item")

    assert item.findtext("title") == "Episode 3"
    assert item.findtext("description") == "About 3"
    guid = item.find("guid")
    assert guid is not None and guid.text == str(episode.id)
    assert guid.attrib["isPermaLink"] == "false"
    assert parsedate_to_datetime(item.findtext("pubDate") or "") == episode.published_at
    enclosure = item.find("enclosure")
    assert enclosure is not None
    assert enclosure.attrib["url"] == media_url(BASE, episode.id)
    assert enclosure.attrib["url"].startswith("https://pods.example.com/media/episodes/")
    assert enclosure.attrib["url"].endswith(".mp3")
    assert enclosure.attrib["length"] == str(episode.size_bytes)
    assert enclosure.attrib["type"] == "audio/mpeg"
    assert item.findtext("itunes:duration", namespaces=NS) == "303"
    assert item.findtext("itunes:explicit", namespaces=NS) == "false"
    assert item.findtext("itunes:episodeType", namespaces=NS) == "full"


def test_only_published_episodes_with_audio_are_listed_newest_first() -> None:
    show = make_show()
    episodes = [
        make_episode(show, 1),
        make_episode(show, 2, status=EpisodeStatus.DRAFT, published_at=None),
        make_episode(show, 3, status=EpisodeStatus.REJECTED, published_at=None),
        make_episode(show, 4, audio_key=None),
        make_episode(show, 5),
    ]

    items = parse(show, episodes).findall("item")

    assert [i.findtext("title") for i in items] == ["Episode 5", "Episode 1"]
    assert [i.findtext("itunes:episode", namespaces=NS) for i in items] == ["2", "1"]


def test_guids_do_not_depend_on_the_address_the_feed_is_served_from() -> None:
    show = make_show()
    episode = make_episode(show, 1)

    first = ET.fromstring(build_feed(show, [episode], "https://a.example.com"))
    second = ET.fromstring(build_feed(show, [episode], "https://b.example.org/podcasts"))

    assert first.findtext("channel/item/guid") == second.findtext("channel/item/guid")
    assert first.findtext("channel/item/guid") == str(episode.id)


def test_text_is_escaped() -> None:
    show = make_show(title="Tom & Jerry <live>", description='5 > 3 & "quotes"')
    episode = make_episode(show, 1, title="A & B", description="<script>x</script>")

    channel = parse(show, [episode])

    assert channel.findtext("title") == "Tom & Jerry <live>"
    assert channel.findtext("description") == '5 > 3 & "quotes"'
    assert channel.findtext("item/description") == "<script>x</script>"


def test_the_feed_is_the_same_every_time() -> None:
    show = make_show()
    episodes = [make_episode(show, 1), make_episode(show, 2)]

    assert build_feed(show, episodes, BASE) == build_feed(show, list(reversed(episodes)), BASE)


def test_urls_are_built_from_the_public_base_url() -> None:
    assert feed_url("https://x.test/", "s") == "https://x.test/feeds/s.xml"
    assert feed_url("https://x.test", "s") == "https://x.test/feeds/s.xml"
    assert media_url("https://x.test/", uuid.UUID(int=7)).endswith(
        "/media/episodes/00000000-0000-0000-0000-000000000007.mp3"
    )


def test_the_podcast_guid_matches_the_specification_example() -> None:
    # podcastindex.org: the feed https://mypodcast.com/rss/ ... is hashed without scheme.
    assert podcast_guid("https://example.com/feed.xml") == podcast_guid(
        "http://example.com/feed.xml"
    )
    assert podcast_guid("https://example.com/feed.xml") != podcast_guid("https://example.com/other")
