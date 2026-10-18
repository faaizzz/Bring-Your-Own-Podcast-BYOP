import calendar
import re
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _aware(value: datetime) -> datetime:
    # A time without a zone (or the RFC 822 "-0000") is taken to be UTC.
    return (value.replace(tzinfo=UTC) if value.tzinfo is None else value).astimezone(UTC)


def parse_date(value: str | None) -> datetime | None:
    """A timezone-aware UTC datetime from an RFC 822 (RSS) or ISO 8601 (Atom, JSON) string."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        if _ISO.match(text):
            return _aware(
                datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))
            )
        return _aware(parsedate_to_datetime(text))
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def from_struct(stamp: time.struct_time | tuple[int, ...] | None) -> datetime | None:
    """feedparser's own parse of an entry date (UTC), as an aware datetime."""
    if not stamp:
        return None
    try:
        return datetime.fromtimestamp(calendar.timegm(stamp), UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
