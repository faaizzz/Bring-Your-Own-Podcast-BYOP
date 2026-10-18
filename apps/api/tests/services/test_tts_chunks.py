import re

import pytest

from byop.services.tts_chunks import split_text


def squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def test_short_text_is_one_chunk() -> None:
    assert split_text("Hello there. How are you?", 100) == ["Hello there. How are you?"]


def test_text_is_cut_at_sentence_boundaries() -> None:
    text = "First sentence here. Second sentence follows! Is there a third one? Yes, there is."

    chunks = split_text(text, 45)

    assert chunks == [
        "First sentence here.",
        "Second sentence follows!",
        "Is there a third one? Yes, there is.",
    ]
    assert all(len(c) <= 45 for c in chunks)


def test_sentences_are_packed_into_chunks_as_full_as_the_limit_allows() -> None:
    text = " ".join(f"Sentence number {n} ends here." for n in range(1, 9))

    chunks = split_text(text, 70)

    assert [c.count("Sentence") for c in chunks] == [2, 2, 2, 2]
    assert squash("".join(chunks)) == squash(text)


def test_a_sentence_longer_than_the_limit_is_cut_at_commas_then_spaces() -> None:
    text = "This is a long sentence, with several clauses, and it just keeps on going, and going."

    by_clause = split_text(text, 40)
    by_word = split_text("word " * 30, 40)

    assert all(len(c) <= 40 for c in by_clause + by_word)
    assert by_clause[0].endswith(",") and len(by_clause) > 1
    assert squash("".join(by_clause)) == squash(text)
    assert all(c.split() == ["word"] * len(c.split()) for c in by_word)  # no word is broken


def test_an_unbreakable_run_of_characters_is_cut_anywhere() -> None:
    chunks = split_text("x" * 250, 100)

    assert chunks == ["x" * 100, "x" * 100, "x" * 50]


def test_cjk_text_is_cut_at_its_own_sentence_marks() -> None:
    chunks = split_text("你好。这是一个测试！你觉得怎么样？非常好。", 9)

    assert chunks == ["你好。这是一个测试！", "你觉得怎么样？", "非常好。"] or all(
        len(c) <= 9 for c in chunks
    )
    assert "".join(chunks) == "你好。这是一个测试！你觉得怎么样？非常好。"
    assert all(c.endswith(("。", "！", "？")) for c in chunks)


def test_quotes_and_brackets_stay_with_their_sentence() -> None:
    chunks = split_text('He said "stop." Then (quietly) he left. She stayed.', 30)

    assert chunks[0] == 'He said "stop."'
    assert all(not c.startswith(('"', ")")) for c in chunks)


def test_line_breaks_separate_sentences_and_nothing_is_lost() -> None:
    text = "A headline without a full stop\nthen a proper sentence. And one more"

    chunks = split_text(text, 35)

    assert squash("".join(chunks)) == squash(text)
    assert all(len(c) <= 35 for c in chunks)


@pytest.mark.parametrize("text", ["", "   ", "\n\n"])
def test_nothing_to_say_gives_no_chunks(text: str) -> None:
    assert split_text(text, 50) == []


@pytest.mark.parametrize("limit", [1, 2, 7, 25, 80, 4096])
def test_every_chunk_fits_and_the_text_is_preserved(limit: int) -> None:
    text = (
        "Researchers have mapped the ocean floor, in unprecedented detail! The data, which took "
        "years to collect, shows ridges, canyons and volcanoes. Why does it matter? Because maps "
        "guide everything from cables to conservation... 地图很重要。真的！"
    )

    chunks = split_text(text, limit)

    assert chunks and all(0 < len(c) <= limit for c in chunks)
    assert squash("".join(chunks)) == squash(text)


def test_the_limit_must_be_positive() -> None:
    with pytest.raises(ValueError):
        split_text("hello", 0)
