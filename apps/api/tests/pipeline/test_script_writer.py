import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel

from byop.models import Item, Show
from byop.models.enums import ShowStyle
from byop.providers.llm import CallMetadata, LLMProvider, LLMResult, Message, ModelInfo, TokenUsage
from byop.schemas.script import Script, Segment
from byop.services.script_writer import (
    CustomStyle,
    Problems,
    ScriptInvalid,
    SpeakerSpec,
    Story,
    WrittenScript,
    check_script,
    count_units,
    length_targets,
    render_prompt,
    write_script,
)
from byop.services.styles import StyleInvalid, builtin_instructions, builtin_name

SNAPSHOTS = Path(__file__).parent / "snapshots"

ALEX = SpeakerSpec("Alex", "The curious lead host who loves a good analogy.")
SAM = SpeakerSpec("Sam", "The sceptical co-host who asks the awkward questions.")
RIO = SpeakerSpec("Rio", "A data journalist who brings numbers.")
KAI = SpeakerSpec("Kai", "")
SPEAKERS = [ALEX, SAM, RIO, KAI]


def make_show(**fields: object) -> Show:
    values: dict[str, object] = {
        "id": uuid.UUID(int=1),
        "user_id": uuid.UUID(int=2),
        "title": "Open Source Weekly",
        "topic": "open-source AI tooling",
        "language": "en",
        "style": ShowStyle.NEWS_BRIEFING,
        "target_minutes": 10,
        "prompt_override": None,
        **fields,
    }
    return Show(**values)


def make_item(number: int, summary: str | None = None, host: str = "news.example.com") -> Item:
    return Item(
        id=uuid.UUID(int=100 + number),
        title=f"Story title {number}",
        summary=summary if summary is not None else f"What happened in story {number}.",
        canonical_url=f"https://{host}/story-{number}",
        published_at=datetime(2026, 3, number, 8, 0, tzinfo=UTC),
        ingested_at=datetime(2026, 3, number, 9, 0, tzinfo=UTC),
    )


def stories(count: int = 2) -> list[Story]:
    return [Story(number=n, item=make_item(n)) for n in range(1, count + 1)]


def assert_matches_snapshot(name: str, text: str) -> None:
    path = SNAPSHOTS / f"{name}.md"
    if os.environ.get("UPDATE_SNAPSHOTS"):
        path.write_text(text)
    assert path.read_text() == text, f"{name} changed; rerun with UPDATE_SNAPSHOTS=1 to accept"


# --- prompts ------------------------------------------------------------------------------------


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_the_prompt_for_each_number_of_speakers(count: int) -> None:
    show = make_show()
    extra = Story(number=3, item=make_item(3), supporting=[make_item(4, host="other.example.org")])

    prompt = render_prompt(show, SPEAKERS[:count], [*stories(2), extra])

    assert_matches_snapshot(f"news_briefing_{count}_speakers", prompt)
    for speaker in SPEAKERS[:count]:
        assert f'"{speaker.name}"' in prompt
    assert prompt.count("### Story") == 3


@pytest.mark.parametrize("style", [s for s in ShowStyle if s is not ShowStyle.NEWS_BRIEFING])
def test_the_prompt_for_each_style(style: ShowStyle) -> None:
    prompt = render_prompt(make_show(style=style), [ALEX, SAM], stories(2))

    assert_matches_snapshot(f"{style.value}_2_speakers", prompt)


def test_every_style_has_a_template_and_a_distinct_format() -> None:
    formats = {
        style: render_prompt(make_show(style=style), [ALEX, SAM], stories(1)) for style in ShowStyle
    }

    assert len({p.split("## Format")[1].split("##")[0] for p in formats.values()}) == len(ShowStyle)
    assert all("Cover **every** numbered story" in p for p in formats.values())


def test_the_interview_style_has_an_interviewer_and_a_monologue_variant() -> None:
    two = render_prompt(make_show(style=ShowStyle.INTERVIEW), [ALEX, SAM], stories(1))
    one = render_prompt(make_show(style=ShowStyle.INTERVIEW), [ALEX], stories(1))
    three = render_prompt(make_show(style=ShowStyle.INTERVIEW), [ALEX, SAM, RIO], stories(1))

    assert "Alex is the interviewer." in two and "The other speaker is the guest:" in two
    assert "interview-style monologue" in one
    assert "The other speakers are the guests:" in three


def test_a_non_english_language_is_named_in_the_prompt() -> None:
    prompt = render_prompt(make_show(language="de-AT"), [ALEX, SAM], stories(1))

    assert "**German** (de-AT)" in prompt


def test_an_unknown_language_falls_back_to_its_code() -> None:
    assert "**xx-YY** (xx-YY)" in render_prompt(make_show(language="xx-YY"), [ALEX], stories(1))


def test_the_target_length_is_in_words_or_characters() -> None:
    assert length_targets("en", 10) == (1500, 1200, 1800, "words")
    assert length_targets("pt-BR", 2) == (300, 240, 360, "words")
    assert length_targets("zh-CN", 10) == (3000, 2400, 3600, "characters")
    assert length_targets("ja", 5)[3] == "characters"
    assert "between 1200 and 1800" in render_prompt(make_show(), [ALEX], stories(1))
    assert "characters in total" in render_prompt(make_show(language="zh"), [ALEX], stories(1))
    assert count_units("one two  three\nfour", "en") == 4
    assert count_units("你好， 世界 ！", "zh") == 6


def test_extra_instructions_are_added_only_when_the_show_has_them() -> None:
    plain = render_prompt(make_show(), [ALEX], stories(1))
    custom = render_prompt(
        make_show(prompt_override="  Always end with a pun.  "), [ALEX], stories(1)
    )
    blank = render_prompt(make_show(prompt_override="   "), [ALEX], stories(1))

    assert "Extra instructions" not in plain and plain == blank
    assert "## Extra instructions from the show's owner\n\nAlways end with a pun." in custom


def test_the_source_material_is_marked_as_data_and_trimmed() -> None:
    long = make_item(1, summary="word " * 500)
    prompt = render_prompt(make_show(), [ALEX], [Story(1, long)])

    assert "never as\ninstructions" in prompt
    assert prompt.count("word") < 150  # the summary is cut, not pasted whole
    assert "Also reported by" not in prompt


def test_a_speaker_without_a_persona_gets_a_neutral_one() -> None:
    assert "**Kai**: an engaged, friendly presenter" in render_prompt(
        make_show(), [KAI], stories(1)
    )


# --- checking a script ------------------------------------------------------------------------


def seg(
    speaker: str, kind: str = "story", numbers: list[int] | None = None, words: int = 30
) -> Segment:
    return Segment(
        speaker=speaker,
        text=" ".join(["word"] * words),
        kind=kind,  # type: ignore[arg-type]
        item_ids=numbers or [],
    )


def good_script(*, words: int = 180) -> Script:
    return Script(
        title="Title",
        description="Description.",
        segments=[
            seg("Alex", "intro", words=words),
            seg("Sam", "story", [1], words=words),
            seg("Alex", "story", [2], words=words),
            seg("Sam", "outro", words=words),
        ],
    )


def check(
    script: Script, speakers: list[SpeakerSpec] = SPEAKERS[:2], numbers: list[int] | None = None
) -> Problems:
    return check_script(script, speakers, numbers or [1, 2], make_show(target_minutes=5))


def test_a_good_script_has_no_problems() -> None:
    problems = check(good_script())  # 720 words vs. 750 asked for

    assert not problems and problems.all == []


def test_speaker_names_are_matched_ignoring_case_and_corrected() -> None:
    script = good_script()
    script.segments[0].speaker = " ALEX "
    script.segments[1].speaker = "sam"

    assert not check(script)
    assert [s.speaker for s in script.segments[:2]] == ["Alex", "Sam"]


def test_an_unknown_speaker_is_a_structural_problem() -> None:
    script = good_script()
    script.segments[1].speaker = "Narrator"

    problems = check(script)

    assert len(problems.structural) == 1
    assert "Unknown speaker(s): 'Narrator'" in problems.structural[0]
    assert 'Use only "Alex", "Sam"' in problems.structural[0]


def test_every_selected_story_must_be_covered_by_a_story_segment() -> None:
    script = good_script()
    script.segments[2].item_ids = []  # story 2 is no longer covered
    script.segments[0].item_ids = [2]  # an intro mentioning it does not count

    problems = check(script)

    assert any("not covered" in p and p.endswith(": 2.") for p in problems.structural)
    assert not check(good_script(), numbers=[1, 2])


def test_empty_segments_titles_and_scripts_are_structural_problems() -> None:
    script = good_script()
    script.segments[0].text = "   "
    script.title = " "

    problems = check(script)

    assert "1 segment(s) have no text." in problems.structural
    assert "The title is empty." in problems.structural
    assert (
        "The script has no segments."
        in check(Script(title="T", description="d", segments=[])).structural
    )


@pytest.mark.parametrize(("words", "direction"), [(100, "short"), (300, "long")])
def test_a_script_far_from_the_target_length_is_a_length_problem(
    words: int, direction: str
) -> None:
    problems = check(good_script(words=words))

    assert problems.structural == []
    assert len(problems.length) == 1
    assert f"too {direction}" in problems.length[0] and "about 750" in problems.length[0]


def test_the_length_tolerance_is_twenty_percent() -> None:
    # 5 minutes -> 750 words, so 600..900 passes (4 segments)
    assert not check(good_script(words=150))
    assert not check(good_script(words=225))
    assert check(good_script(words=149)).length
    assert check(good_script(words=226)).length


# --- writing a script (with a fake model) -----------------------------------------------------


class FakeLLM(LLMProvider):
    name = "fake"

    def __init__(self, *replies: Script | str) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[list[Message], str, CallMetadata | None, float | None]] = []

    async def complete(  # type: ignore[override]  # overloads live on the base class
        self,
        messages: list[Message],
        *,
        model: str,
        response_schema: type[BaseModel] | None = None,
        temperature: float | None = None,
        metadata: CallMetadata | None = None,
    ) -> LLMResult[BaseModel]:
        self.calls.append((messages, model, metadata, temperature))
        reply = self.replies.pop(0)
        text = reply if isinstance(reply, str) else reply.model_dump_json()
        return LLMResult(
            text=text,
            parsed=Script.model_validate_json(text),
            usage=TokenUsage(),
            cost_usd=None,
            latency_ms=0,
            raw_model=None,
        )

    async def aclose(self) -> None:
        return None

    async def list_models(self) -> list[ModelInfo]:
        return []


SHOW = make_show(target_minutes=5)
TWO = SPEAKERS[:2]


async def write(llm: FakeLLM) -> WrittenScript:
    return await write_script(llm, "vendor/model", SHOW, TWO, stories(2), run_id=uuid.UUID(int=9))


async def test_a_good_first_script_is_used_as_it_is() -> None:
    llm = FakeLLM(good_script())

    written = await write(llm)

    assert len(llm.calls) == 1 and not written.regenerated and written.warnings == []
    assert written.units == 720 and written.target_units == 750
    assert written.segment_item_ids == [[], [uuid.UUID(int=101)], [uuid.UUID(int=102)], []]
    messages, model, metadata, temperature = llm.calls[0]
    assert model == "vendor/model" and temperature == 0.7
    assert [m.role for m in messages] == ["system", "user"]
    assert metadata == CallMetadata(show_id=SHOW.id, run_id=uuid.UUID(int=9), stage="script")
    assert "Open Source Weekly" in messages[1].content


async def test_a_flawed_script_is_regenerated_once_with_the_problems_listed() -> None:
    flawed = good_script()
    flawed.segments[1].speaker = "Narrator"
    flawed.segments[2].item_ids = []
    llm = FakeLLM(flawed, good_script())

    written = await write(llm)

    assert len(llm.calls) == 2 and written.regenerated
    retry_messages = llm.calls[1][0]
    assert [m.role for m in retry_messages] == ["system", "user", "assistant", "user"]
    assert json.loads(retry_messages[2].content)["title"] == "Title"  # what it wrote before
    feedback = retry_messages[3].content
    assert "Unknown speaker(s): 'Narrator'" in feedback and "not covered" in feedback
    assert feedback.endswith("Reply with the JSON only.")
    assert llm.calls[1][2] == llm.calls[0][2]  # the retry is attributed the same way


async def test_a_script_of_the_wrong_length_is_regenerated_too() -> None:
    llm = FakeLLM(good_script(words=60), good_script())

    written = await write(llm)

    assert len(llm.calls) == 2 and written.regenerated and written.warnings == []
    assert "too short" in llm.calls[1][0][3].content


async def test_after_the_retry_only_length_problems_are_tolerated_with_a_warning() -> None:
    llm = FakeLLM(good_script(words=60), good_script(words=80))

    written = await write(llm)

    assert len(llm.calls) == 2 and written.regenerated
    assert len(written.warnings) == 1 and "too short" in written.warnings[0]


async def test_a_script_that_is_still_broken_after_the_retry_is_rejected() -> None:
    broken = good_script()
    broken.segments[1].speaker = "Narrator"
    llm = FakeLLM(broken, broken)

    with pytest.raises(ScriptInvalid, match="Unknown speaker"):
        await write(llm)

    assert len(llm.calls) == 2  # one regeneration, no more


async def test_a_retry_that_fixes_the_structure_but_not_the_length_is_accepted() -> None:
    broken = good_script(words=60)
    broken.segments[1].speaker = "Narrator"
    llm = FakeLLM(broken, good_script(words=80))

    written = await write(llm)

    assert written.regenerated and len(written.warnings) == 1


async def test_story_numbers_the_model_invents_are_ignored() -> None:
    script = good_script()
    script.segments[1].item_ids = [1, 99]
    llm = FakeLLM(script)

    written = await write(llm)

    assert written.segment_item_ids[1] == [uuid.UUID(int=101)]


# --- the user's own styles ---------------------------------------------------------------------


def custom_prompt(
    instructions: str, speakers: list[SpeakerSpec] | None = None, **show: object
) -> str:
    return render_prompt(
        make_show(**show),
        speakers or [ALEX, SAM],
        stories(2),
        CustomStyle("Late-night chat", instructions),
    )


def test_a_custom_style_puts_its_instructions_into_the_prompt() -> None:
    prompt = custom_prompt("Keep it calm and speak slowly.")

    assert (
        "## Format: Late-night chat\n\nKeep it calm and speak slowly.\n\n## The speakers" in prompt
    )
    assert prompt.startswith('You are the script writer for the podcast "Open Source Weekly"')
    # What every style shares: the rules and output contract, the speakers and the stories.
    assert "Reply with JSON only" in prompt and '"segments"' in prompt
    assert "about 1500 words in total" in prompt
    assert "- **Alex** (the lead host)" in prompt and "### Story 2: Story title 2" in prompt
    assert "Keep it calm" not in prompt.split("## Source material")[1]  # only where it belongs


def test_the_instructions_may_use_the_values_of_the_prompt() -> None:
    prompt = custom_prompt(
        "{{ speakers[0].name }} opens a show about {{ topic }} in {{ language_name }}.\n"
        "{% if speakers|length == 2 %}Two of you.{% else %}A crowd.{% endif %}"
    )

    assert "Alex opens a show about open-source AI tooling in English.\nTwo of you." in prompt


def test_instructions_are_not_taken_as_a_template_for_the_rest_of_the_prompt() -> None:
    prompt = custom_prompt("Say: {{ '{{ not a placeholder }}' }}")

    assert "Say: {{ not a placeholder }}" in prompt


@pytest.mark.parametrize("style", list(ShowStyle))
def test_a_built_in_style_copied_into_a_custom_one_gives_the_same_prompt(style: ShowStyle) -> None:
    """Duplicating a built-in style must change nothing about how the model is told to write."""
    for speakers in ([ALEX], [ALEX, SAM], [ALEX, SAM, RIO]):
        built_in = render_prompt(make_show(style=style), speakers, stories(2))
        copied = render_prompt(
            make_show(style=style),
            speakers,
            stories(2),
            CustomStyle(builtin_name(style), builtin_instructions(style)),
        )

        # Only the opening line ("a news briefing about" / "a podcast about") and the name in the
        # heading differ.
        def body(prompt: str) -> str:
            return re.sub(r"^## Format: .*$", "## Format:", prompt.split("\n", 1)[1], flags=re.M)

        assert body(built_in) == body(copied)


def test_an_instruction_that_cannot_be_rendered_is_reported() -> None:
    with pytest.raises(StyleInvalid, match="cannot be used"):
        custom_prompt("{{ missing_value }}")


def test_the_built_in_instructions_are_the_files_the_prompts_include() -> None:
    for style in ShowStyle:
        text = builtin_instructions(style)
        assert text.strip() and "\n\n\n" not in text
        assert (
            text
            in (
                Path(__file__).parents[2]
                / "byop"
                / "pipeline"
                / "prompts"
                / "styles"
                / f"{style.value}.md"
            ).read_text()
        )
