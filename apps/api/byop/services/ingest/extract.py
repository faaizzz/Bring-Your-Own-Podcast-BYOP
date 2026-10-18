import html
import re
from dataclasses import dataclass

import lxml.etree
import lxml.html
from readability import Document
from readability.readability import Unparseable

MAX_SUMMARY_CHARS = 2000
_TAGS = re.compile(r"<[^>]+>")
_CHARSET = re.compile(r"charset=([\w-]+)", re.IGNORECASE)


def strip_html(text: str) -> str:
    """Plain text from an HTML fragment (feed summaries are often marked up)."""
    return " ".join(html.unescape(_TAGS.sub(" ", text)).split())


def decode(content: bytes, content_type: str | None) -> str:
    match = _CHARSET.search(content_type or "")
    for encoding in (match.group(1) if match else None, "utf-8"):
        if encoding:
            try:
                return content.decode(encoding)
            except (LookupError, UnicodeDecodeError):
                continue
    return content.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class Page:
    title: str
    text: str


def extract_page(markup: str) -> Page | None:
    """The title and main text of a web page, without navigation and boilerplate."""
    try:
        document = Document(markup)
        title = " ".join((document.short_title() or "").split())
        body = document.summary(html_partial=True)
        text = " ".join(lxml.html.fromstring(body).text_content().split())
    except (Unparseable, ValueError, lxml.etree.ParserError):
        return None
    if not text:
        return None
    return Page(title=title, text=text)
