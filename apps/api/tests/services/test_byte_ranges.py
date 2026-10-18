import pytest

from byop.services.byte_ranges import ByteRange, RangeNotSatisfiable, parse_range


@pytest.mark.parametrize(
    ("header", "size", "expected"),
    [
        ("bytes=0-99", 1000, ByteRange(0, 99)),
        ("bytes=500-", 1000, ByteRange(500, 999)),
        ("bytes=-100", 1000, ByteRange(900, 999)),
        ("bytes=-5000", 1000, ByteRange(0, 999)),  # a suffix longer than the file is all of it
        ("bytes=900-5000", 1000, ByteRange(900, 999)),  # an end past the file is clamped
        ("bytes=7-7", 1000, ByteRange(7, 7)),
        (None, 1000, None),
        ("", 1000, None),
        ("items=0-1", 1000, None),  # a unit we do not know: serve everything
        ("bytes=0-1,5-6", 1000, None),  # several ranges: serve everything
        ("bytes=abc-def", 1000, None),
        ("bytes=9-3", 1000, None),
    ],
)
def test_parse_range(header: str | None, size: int, expected: ByteRange | None) -> None:
    assert parse_range(header, size) == expected


@pytest.mark.parametrize("header", ["bytes=1000-", "bytes=2000-3000", "bytes=-0"])
def test_a_range_outside_the_file_is_not_satisfiable(header: str) -> None:
    with pytest.raises(RangeNotSatisfiable):
        parse_range(header, 1000)


def test_a_range_covers_its_end_byte() -> None:
    assert ByteRange(10, 19).length == 10
