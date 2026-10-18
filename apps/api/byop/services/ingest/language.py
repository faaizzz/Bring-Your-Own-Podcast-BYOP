from langdetect import DetectorFactory, detect_langs
from langdetect.lang_detect_exception import LangDetectException

DetectorFactory.seed = 0  # the same text always gets the same answer

MIN_CHARS = 25  # shorter text is too ambiguous to judge
MIN_PROBABILITY = 0.7


def detect_language(text: str) -> str | None:
    """The language of `text` as a base code like `en`, or None when it cannot be told."""
    sample = text.strip()
    if len(sample) < MIN_CHARS:
        return None
    try:
        best = detect_langs(sample)[0]
    except LangDetectException:
        return None
    if best.prob < MIN_PROBABILITY:
        return None
    return str(best.lang).split("-")[0].lower()  # langdetect says zh-cn, zh-tw


def matches_language(detected: str | None, show_language: str) -> bool:
    """Keep an item unless it is confidently in another language than the show's."""
    if detected is None:
        return True
    return detected == show_language.split("-")[0].lower()
