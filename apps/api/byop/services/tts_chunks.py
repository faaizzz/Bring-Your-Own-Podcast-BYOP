"""Cutting a script's text into pieces a TTS provider accepts, at natural boundaries."""

import re

# A sentence: up to and including its end mark (and closing quotes/brackets and the space after),
# or a CJK end mark, or a line break, or the end of the text.
_SENTENCE = re.compile(
    r".+?(?:[.!?…]+[\"'”’)\]]*(?:\s+|$)|[。！？]+[”’」』）]*|\n+|$)",
    re.DOTALL,
)
_CLAUSE = re.compile(r".+?(?:[,;:，、；：]\s*|$)", re.DOTALL)
_WORD = re.compile(r"\S+\s*")


def _pack(parts: list[str], limit: int) -> list[str]:
    """Join consecutive parts (they keep their own spacing) into pieces of at most `limit`."""
    pieces: list[str] = []
    current = ""
    for part in parts:
        if current and len(current) + len(part) > limit:
            pieces.append(current)
            current = ""
        current += part
    if current:
        pieces.append(current)
    return pieces


def _hard_split(text: str, limit: int) -> list[str]:
    return [text[i : i + limit] for i in range(0, len(text), limit)]


def _split_long(text: str, limit: int) -> list[str]:
    """A sentence longer than the limit: at commas and the like, then at spaces, then anywhere."""
    pieces: list[str] = []
    for clause in _pack(_CLAUSE.findall(text), limit):
        if len(clause) <= limit:
            pieces.append(clause)
            continue
        for words in _pack(_WORD.findall(clause), limit):
            pieces.extend([words] if len(words) <= limit else _hard_split(words, limit))
    return pieces


def split_text(text: str, limit: int) -> list[str]:
    """Pieces of at most `limit` characters that together are the text.

    Pieces end at sentence boundaries wherever the text allows it, and a sentence is only cut
    (at a comma, a space, and as a last resort anywhere) when it is longer than the limit
    itself. Pieces are trimmed and never empty.
    """
    if limit < 1:
        raise ValueError("limit must be positive")
    sentences = [s for s in _SENTENCE.findall(text.strip()) if s]
    parts: list[str] = []
    for sentence in sentences:
        parts.extend([sentence] if len(sentence) <= limit else _split_long(sentence, limit))
    return [piece.strip() for piece in _pack(parts, limit) if piece.strip()]
