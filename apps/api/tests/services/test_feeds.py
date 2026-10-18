import pytest

from byop.services.feeds import FeedInvalid, parse_feed

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>  Daily Rust  </title><link>https://example.com</link><description>d</description>
  <item><title>First story</title><link>https://example.com/1</link></item>
  <item><title>Second story</title><link>https://example.com/2</link></item>
  <item><title>Third story</title><link>https://example.com/3</link></item>
  <item><title>Fourth story</title><link>https://example.com/4</link></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Blog</title><id>urn:x</id><updated>2026-01-01T00:00:00Z</updated>
  <entry><title>Hello Atom</title><id>urn:1</id><updated>2026-01-01T00:00:00Z</updated></entry>
</feed>"""

RDF = b"""<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/">
  <channel rdf:about="https://example.com"><title>RDF Feed</title><link>https://example.com</link></channel>
  <item rdf:about="https://example.com/1"><title>Old style</title><link>https://example.com/1</link></item>
</rdf:RDF>"""


def test_rss_gives_the_title_count_and_three_latest_titles() -> None:
    preview = parse_feed(RSS)

    assert preview.title == "Daily Rust"
    assert preview.entry_count == 4
    assert preview.latest_titles == ["First story", "Second story", "Third story"]


def test_atom_and_rdf_feeds_are_understood() -> None:
    atom = parse_feed(ATOM)
    rdf = parse_feed(RDF)

    assert (atom.title, atom.latest_titles) == ("Atom Blog", ["Hello Atom"])
    assert (rdf.title, rdf.latest_titles) == ("RDF Feed", ["Old style"])


def test_an_empty_feed_is_valid() -> None:
    preview = parse_feed(
        b'<?xml version="1.0"?><rss version="2.0"><channel><title>New</title></channel></rss>'
    )

    assert preview.title == "New" and preview.entry_count == 0 and preview.latest_titles == []


def test_entries_without_titles_are_skipped_in_the_preview() -> None:
    preview = parse_feed(
        b'<rss version="2.0"><channel><title>T</title>'
        b"<item><link>https://e.com/1</link></item>"
        b"<item><title>Named</title></item></channel></rss>"
    )

    assert preview.entry_count == 2
    assert preview.latest_titles == ["Named"]


def test_very_long_titles_are_shortened() -> None:
    feed = b'<rss version="2.0"><channel><title>T</title><item><title>' + b"x" * 500
    feed += b"</title></item></channel></rss>"

    assert len(parse_feed(feed).latest_titles[0]) == 200


@pytest.mark.parametrize(
    ("content", "content_type", "reason"),
    [
        (b"<!DOCTYPE html><html><head><title>Blog</title></head><body/></html>", None, "web page"),
        (b"<p>whatever</p>", "text/html; charset=utf-8", "web page"),
        (b"just some text", "text/plain", "not a valid RSS or Atom feed"),
        (b'{"feed": "json"}', "application/json", "not a valid RSS or Atom feed"),
        (b"", None, "not a valid RSS or Atom feed"),
        (b"<rss><channel>", None, "empty or damaged"),
        (b"\x00\x01\x02binary", "application/octet-stream", "not a valid RSS or Atom feed"),
    ],
)
def test_things_that_are_not_feeds_are_rejected_with_a_reason(
    content: bytes, content_type: str | None, reason: str
) -> None:
    with pytest.raises(FeedInvalid, match=reason):
        parse_feed(content, content_type)


# --- entries (what ingest reads) ---------------------------------------------------------------


def test_entries_carry_title_link_plain_summary_and_utc_date() -> None:
    from datetime import UTC, datetime

    from byop.services.feeds import parse_entries

    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
    <item><title> First </title><link>https://e.com/1</link>
      <description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</description>
      <pubDate>Mon, 05 Jan 2026 08:30:00 +0100</pubDate></item>
    <item><title>No link</title></item>
    <item><link>https://e.com/3</link></item>
    <item><title>Undated</title><link>https://e.com/4</link></item></channel></rss>"""

    entries = parse_entries(feed)

    assert [e.title for e in entries] == ["First", "Undated"]
    assert entries[0].link == "https://e.com/1" and entries[0].summary == "Hello world"
    assert entries[0].published == datetime(2026, 1, 5, 7, 30, tzinfo=UTC)
    assert entries[1].published is None


def test_entries_from_atom_use_content_when_there_is_no_summary() -> None:
    from byop.services.feeds import parse_entries

    atom = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>A</title>
    <entry><title>Post</title><id>1</id><link href="https://e.com/p"/>
    <updated>2026-01-05T08:30:00Z</updated><content type="html">
    &lt;p&gt;Body text&lt;/p&gt;</content>
    </entry></feed>"""

    [entry] = parse_entries(atom)

    assert entry.summary == "Body text" and entry.published is not None


def test_entries_of_an_empty_feed_are_empty_but_a_non_feed_is_an_error() -> None:
    from byop.services.feeds import parse_entries

    assert parse_entries(b'<rss version="2.0"><channel><title>T</title></channel></rss>') == []
    with pytest.raises(FeedInvalid, match="web page"):
        parse_entries(b"<html><body>x</body></html>", "text/html")
    with pytest.raises(FeedInvalid, match="not a valid"):
        parse_entries(b"")
