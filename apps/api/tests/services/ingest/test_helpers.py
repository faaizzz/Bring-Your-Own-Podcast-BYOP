from datetime import UTC, datetime, timedelta

import pytest

from byop.services.ingest.canonical import canonical_url, content_hash
from byop.services.ingest.dates import from_struct, parse_date
from byop.services.ingest.extract import decode, extract_page, strip_html
from byop.services.ingest.language import detect_language, matches_language

# --- canonical URLs --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://Example.com/Story", "https://example.com/Story"),
        ("https://www.example.com/story", "https://example.com/story"),
        ("http://example.com/story", "https://example.com/story"),
        ("https://example.com/story/", "https://example.com/story"),
        ("https://example.com/story#comments", "https://example.com/story"),
        ("https://example.com", "https://example.com/"),
        ("https://example.com:443/story", "https://example.com/story"),
        ("http://example.com:80/story", "https://example.com/story"),
        ("https://example.com:8443/story", "https://example.com:8443/story"),
        ("https://example.com/a//b///c", "https://example.com/a/b/c"),
        ("https://example.com./story", "https://example.com/story"),
        ("  https://example.com/story  ", "https://example.com/story"),
        (
            "https://example.com/s?utm_source=x&id=7&utm_medium=y&fbclid=abc&gclid=1",
            "https://example.com/s?id=7",
        ),
        (
            "https://www.bbc.co.uk/news/articles/c8vg?at_campaign=rss&at_medium=RSS&at_custom1=x",
            "https://bbc.co.uk/news/articles/c8vg",
        ),
        (
            "https://example.com/p?pk_campaign=a&mtm_source=b&id=9&si=abc",
            "https://example.com/p?id=9",
        ),
        # parameters that can identify content are kept
        ("https://example.com/p?cid=77&source=feed", "https://example.com/p?cid=77&source=feed"),
        ("https://example.com/s?b=2&a=1", "https://example.com/s?a=1&b=2"),
        ("https://example.com/s?a=1&utm_campaign=z#top", "https://example.com/s?a=1"),
        ("https://example.com/s?UTM_Source=x&ref=twitter&page=2", "https://example.com/s?page=2"),
    ],
)
def test_canonical_url(url: str, expected: str) -> None:
    assert canonical_url(url) == expected


def test_different_spellings_of_one_page_agree() -> None:
    spellings = [
        "https://www.Example.com/news/ai?utm_source=a&id=3#x",
        "http://example.com/news/ai/?id=3&fbclid=zzz",
        "https://example.com:443/news//ai?id=3",
    ]

    assert len({canonical_url(s) for s in spellings}) == 1


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a url",
        "ftp://example.com/x",
        "javascript:alert(1)",
        "mailto:a@b.c",
        "http://",
        "https://[bad",
    ],
)
def test_unusable_urls_have_no_canonical_form(url: str) -> None:
    assert canonical_url(url) is None


def test_overlong_urls_are_refused() -> None:
    assert canonical_url("https://example.com/" + "a" * 2100) is None


def test_content_hash_ignores_case_and_spacing_but_not_words() -> None:
    assert content_hash("Hello  World", "Some   text") == content_hash("hello world", "some text")
    assert content_hash("Hello World", "Some text") != content_hash("Hello World", "Other text")
    assert len(content_hash("a", "b")) == 64


# --- dates -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # RFC 822 / 2822, as RSS writes them
        ("Mon, 05 Jan 2026 08:30:00 GMT", datetime(2026, 1, 5, 8, 30, tzinfo=UTC)),
        ("Mon, 05 Jan 2026 08:30:00 +0100", datetime(2026, 1, 5, 7, 30, tzinfo=UTC)),
        ("Mon, 5 Jan 2026 08:30 -0500", datetime(2026, 1, 5, 13, 30, tzinfo=UTC)),
        ("05 Jan 2026 08:30:00 UT", datetime(2026, 1, 5, 8, 30, tzinfo=UTC)),
        ("Mon, 05 Jan 2026 08:30:00 -0000", datetime(2026, 1, 5, 8, 30, tzinfo=UTC)),
        # ISO 8601, as Atom and JSON write them
        ("2026-01-05T08:30:00Z", datetime(2026, 1, 5, 8, 30, tzinfo=UTC)),
        ("2026-01-05T08:30:00+01:00", datetime(2026, 1, 5, 7, 30, tzinfo=UTC)),
        ("2026-01-05T08:30:00.123456-05:00", datetime(2026, 1, 5, 13, 30, 0, 123456, tzinfo=UTC)),
        ("2026-01-05T08:30:00", datetime(2026, 1, 5, 8, 30, tzinfo=UTC)),  # no zone: UTC
        ("2026-01-05", datetime(2026, 1, 5, tzinfo=UTC)),
        ("2026-01-05 08:30:00", datetime(2026, 1, 5, 8, 30, tzinfo=UTC)),
    ],
)
def test_parse_date(text: str, expected: datetime) -> None:
    parsed = parse_date(text)

    assert parsed == expected
    assert parsed is not None and parsed.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    "text", [None, "", "   ", "yesterday", "32 Jan 2026", "2026-13-45", "garbage 123"]
)
def test_unparseable_dates_are_none(text: str | None) -> None:
    assert parse_date(text) is None


def test_rfc822_and_iso_forms_of_the_same_instant_agree() -> None:
    assert parse_date("Tue, 06 Jan 2026 12:00:00 +0200") == parse_date("2026-01-06T10:00:00Z")
    assert parse_date("2026-01-06T12:00:00+02:00") == datetime(2026, 1, 6, 10, tzinfo=UTC)


def test_feedparser_struct_times_become_aware_datetimes() -> None:
    assert from_struct((2026, 1, 5, 8, 30, 0, 0, 5, 0)) == datetime(2026, 1, 5, 8, 30, tzinfo=UTC)
    assert from_struct(None) is None


# --- language -----------------------------------------------------------------------------------

ENGLISH = "The new open source framework makes it much easier to deploy language models locally."
GERMAN = (
    "Das neue Open-Source-Framework macht es deutlich einfacher, Sprachmodelle lokal zu betreiben."
)
FRENCH = "Le nouveau cadre open source permet de déployer très facilement des modèles de langage."


@pytest.mark.parametrize(("text", "code"), [(ENGLISH, "en"), (GERMAN, "de"), (FRENCH, "fr")])
def test_language_detection(text: str, code: str) -> None:
    assert detect_language(text) == code


def test_short_or_empty_text_is_not_judged() -> None:
    assert detect_language("") is None
    assert detect_language("OK") is None
    assert detect_language("Breaking: AI") is None
    assert detect_language("12345 67890 !!! ??? 12345 67890 ###") is None


def test_detection_is_deterministic() -> None:
    assert {detect_language(ENGLISH) for _ in range(5)} == {"en"}


@pytest.mark.parametrize(
    ("detected", "show", "kept"),
    [
        ("en", "en", True),
        ("en", "en-US", True),
        ("en", "EN-gb", True),
        ("de", "de-AT", True),
        ("de", "en", False),
        ("fr", "pt-BR", False),
        (None, "en", True),  # unknown: keep rather than lose a story
    ],
)
def test_the_language_filter(detected: str | None, show: str, kept: bool) -> None:
    assert matches_language(detected, show) is kept


# --- extraction ----------------------------------------------------------------------------------

PARAGRAPH = (
    "We are happy to announce version 2.0 of the project, with a rewritten core, faster startup "
    "and a much smaller memory footprint. The release took a year of work from more than forty "
    "contributors, and it changes how plugins are loaded, how configuration is read and how "
    "errors are reported to the people who run the software every day. "
)
PAGE = f"""<!doctype html><html><head><title>Release 2.0 | Example Project</title></head><body>
<nav><a href="/">Home</a> <a href="/docs">Docs</a> <a href="/blog">Blog</a></nav>
<article><h1>Release 2.0</h1>
<p>{PARAGRAPH}</p>
<p>{PARAGRAPH} Highlights include plugin support, a new configuration format and many fixes.</p>
<p>{PARAGRAPH}</p></article>
<footer>Copyright Example. Privacy. Terms.</footer>
<script>var tracking = true;</script></body></html>"""


def test_extraction_returns_the_title_and_main_text_without_boilerplate() -> None:
    page = extract_page(PAGE)

    assert page is not None
    assert "Release 2.0" in page.title
    assert "rewritten core" in page.text and "plugin support" in page.text
    assert "tracking" not in page.text and "Privacy" not in page.text


@pytest.mark.parametrize(
    "markup", ["", "   ", "<html><body></body></html>", "<script>x()</script>"]
)
def test_pages_without_text_give_nothing(markup: str) -> None:
    assert extract_page(markup) is None


def test_strip_html_gives_plain_text() -> None:
    assert (
        strip_html("<p>Hello&nbsp;<b>world</b> &amp; <a href='x'>friends</a></p>\n\n<br/>!")
        == "Hello world & friends !"
    )


def test_decoding_respects_the_declared_charset() -> None:
    latin = "Café résumé".encode("latin-1")

    assert decode(latin, "text/html; charset=ISO-8859-1") == "Café résumé"
    assert decode("Café".encode(), "text/html") == "Café"
    assert decode(b"\xff\xfe broken", "text/html; charset=nonsense").startswith("�")
