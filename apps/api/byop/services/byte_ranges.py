"""HTTP `Range` headers for serving audio, so players can seek."""

from dataclasses import dataclass


class RangeNotSatisfiable(Exception):
    pass


@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int  # inclusive

    @property
    def length(self) -> int:
        return self.end - self.start + 1


def parse_range(header: str | None, size: int) -> ByteRange | None:
    """The single byte range asked for, or None to serve the whole object.

    Malformed headers and multi-range requests are ignored (the spec allows serving everything);
    a range that starts past the end raises `RangeNotSatisfiable`.
    """
    if not header or not header.startswith("bytes=") or "," in header:
        return None
    first, _, last = header.removeprefix("bytes=").strip().partition("-")
    try:
        if first == "":  # "-N": the final N bytes
            suffix = int(last)
            if suffix <= 0:
                raise RangeNotSatisfiable
            return ByteRange(max(size - suffix, 0), size - 1) if size else None
        start = int(first)
        end = int(last) if last else size - 1
    except ValueError:
        return None
    if start < 0:
        return None
    if start >= size:
        raise RangeNotSatisfiable
    if end < start:
        return None
    return ByteRange(start, min(end, size - 1))
