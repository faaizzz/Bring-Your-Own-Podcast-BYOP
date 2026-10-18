import pytest

from byop.providers.llm.json_extract import extract_json


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1}',
        '  \n{"a": 1}\n ',
        '```json\n{"a": 1}\n```',
        '```\n{"a": 1}\n```',
        'Sure! Here you go:\n```json\n{"a": 1}\n```\nHope that helps.',
        'The answer is {"a": 1} as requested.',
    ],
)
def test_finds_the_object_in_common_reply_shapes(text: str) -> None:
    assert extract_json(text) == {"a": 1}


def test_arrays_and_nesting() -> None:
    assert extract_json('Result: [{"a": {"b": [1, 2]}}, 3] done') == [{"a": {"b": [1, 2]}}, 3]


def test_braces_inside_strings_do_not_confuse_extraction() -> None:
    assert extract_json('text {"a": "x } y"} more') == {"a": "x } y"}


@pytest.mark.parametrize("text", ["", "no json here", "{broken", "```json\nnope\n```"])
def test_raises_when_there_is_no_json(text: str) -> None:
    with pytest.raises(ValueError):
        extract_json(text)
