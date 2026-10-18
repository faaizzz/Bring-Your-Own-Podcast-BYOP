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
