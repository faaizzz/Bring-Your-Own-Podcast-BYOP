"""Writing an episode's script: prompt, structured model call, validation, one retry."""

import re
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import structlog
from jinja2 import Environment, PackageLoader, StrictUndefined

from byop.models import Item, Show
from byop.models.enums import ShowStyle
from byop.providers.llm import CallMetadata, LLMProvider, Message
from byop.schemas.script import Script

log = structlog.get_logger(__name__)

STAGE = "script"
WORDS_PER_MINUTE = 150
# Languages written without spaces between words are measured in characters instead.
CHARS_PER_MINUTE = {"zh": 300, "ja": 400, "ko": 300}
TOLERANCE = 0.2  # the script may be this far from the target length
TEMPERATURE = 0.7

LANGUAGE_NAMES = {
    "en": "English", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian",
    "pt": "Portuguese", "nl": "Dutch", "sv": "Swedish", "da": "Danish", "no": "Norwegian",
    "fi": "Finnish", "pl": "Polish", "cs": "Czech", "tr": "Turkish", "ru": "Russian",
    "uk": "Ukrainian", "el": "Greek", "he": "Hebrew", "ar": "Arabic", "hi": "Hindi",
    "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "id": "Indonesian", "vi": "Vietnamese",
}  # fmt: skip

_templates = Environment(
    loader=PackageLoader("byop.pipeline", "prompts"),
    undefined=StrictUndefined,  # a typo in a template fails loudly instead of rendering nothing
    autoescape=False,  # the prompt is Markdown for a model, not HTML
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)

SYSTEM_PROMPT = (
    "You are an experienced podcast script writer. You write lively, accurate, natural-sounding "
    "dialogue and you always answer with the JSON object that was asked for."
)


class ScriptInvalid(Exception):
    """The model could not produce a usable script, even after being told what was wrong."""


@dataclass(frozen=True)
class SpeakerSpec:
    name: str
    persona: str = ""


@dataclass(frozen=True)
class Story:
    """A chosen story: the main item and the other items that report on the same event."""

    number: int  # as listed in the prompt, starting at 1
    item: Item
    supporting: list[Item] = field(default_factory=list)


@dataclass(frozen=True)
class WrittenScript:
    script: Script
    # Real item ids per segment index, from the story numbers the model gave.
    segment_item_ids: list[list[uuid.UUID]]
    units: int
    target_units: int
    regenerated: bool
    warnings: list[str]


def language_base(language: str) -> str:
    return language.split("-")[0].lower()


def length_targets(language: str, minutes: int) -> tuple[int, int, int, str]:
    """(target, lowest, highest, unit) for an episode of `minutes`, in words or characters."""
    base = language_base(language)
    per_minute = CHARS_PER_MINUTE.get(base, WORDS_PER_MINUTE)
    target = minutes * per_minute
    unit = "characters" if base in CHARS_PER_MINUTE else "words"
    return target, round(target * (1 - TOLERANCE)), round(target * (1 + TOLERANCE)), unit


def count_units(text: str, language: str) -> int:
    if language_base(language) in CHARS_PER_MINUTE:
        return len(re.sub(r"\s+", "", text))
    return len(text.split())


def _host(item: Item) -> str:
    return urlsplit(item.canonical_url).netloc


def _clip(text: str, limit: int = 600) -> str:
    return " ".join(text.split())[:limit]


def render_prompt(show: Show, speakers: list[SpeakerSpec], stories: list[Story]) -> str:
    """The user prompt for the show's style; `ShowStyle` picks the template."""
    target, low, high, unit = length_targets(show.language, show.target_minutes)
    base = language_base(show.language)
    return _templates.get_template(f"{ShowStyle(show.style).value}.md").render(
        show_title=show.title,
        topic=show.topic,
        language=show.language,
        language_name=LANGUAGE_NAMES.get(base, show.language),
        target_minutes=show.target_minutes,
        target_words=target,
        min_words=low,
        max_words=high,
        unit=unit,
        prompt_override=(show.prompt_override or "").strip() or None,
        speakers=speakers,
        stories=[
            {
                "number": story.number,
                "title": story.item.title,
                "host": _host(story.item),
                "published": story.item.published_at.date().isoformat()
                if story.item.published_at
                else None,
                "summary": _clip(story.item.summary),
                "supporting": [
                    {"host": _host(i), "title": i.title, "summary": _clip(i.summary, 300)}
                    for i in story.supporting
                ],
            }
            for story in stories
        ],
    )


@dataclass
class Problems:
    structural: list[str] = field(default_factory=list)  # the script cannot be used as it is
    length: list[str] = field(default_factory=list)  # usable, but not the length asked for

    def __bool__(self) -> bool:
        return bool(self.structural or self.length)

    @property
    def all(self) -> list[str]:
        return [*self.structural, *self.length]


def check_script(
    script: Script, speakers: list[SpeakerSpec], story_numbers: list[int], show: Show
) -> Problems:
    """Everything wrong with `script`. Speaker names are corrected to their exact spelling first
    (the model may change the case), so call this on a script you are going to use."""
    problems = Problems()
    names = {s.name.casefold(): s.name for s in speakers}
    if not script.segments:
        problems.structural.append("The script has no segments.")
    if not script.title.strip():
        problems.structural.append("The title is empty.")
    covered: set[int] = set()
    unknown: set[str] = set()
    empty = 0
    for segment in script.segments:
        canonical = names.get(segment.speaker.strip().casefold())
        if canonical is None:
            unknown.add(segment.speaker)
        else:
            segment.speaker = canonical
        if not segment.text.strip():
            empty += 1
        if segment.kind == "story":
            covered.update(segment.item_ids)
    if unknown:
        allowed = ", ".join(f'"{s.name}"' for s in speakers)
        problems.structural.append(
            f"Unknown speaker(s): {', '.join(sorted(map(repr, unknown)))}. Use only {allowed}."
        )
    if empty:
        problems.structural.append(f"{empty} segment(s) have no text.")
    missing = [n for n in story_numbers if n not in covered]
    if missing:
        problems.structural.append(
            'These stories are not covered by any segment of kind "story" '
            f"(list their numbers in item_ids): {', '.join(map(str, missing))}."
        )
    target, low, high, unit = length_targets(show.language, show.target_minutes)
    units = sum(count_units(s.text, show.language) for s in script.segments)
    if script.segments and not low <= units <= high:
        direction = "short" if units < low else "long"
        problems.length.append(
            f"The script is too {direction}: {units} {unit}, but it should be about {target} "
            f"(between {low} and {high})."
        )
    return problems


def _feedback(problems: Problems) -> str:
    listed = "\n".join(f"- {p}" for p in problems.all)
    return (
        f"Your script has these problems:\n{listed}\n\n"
        "Write the complete script again with all of them fixed. Reply with the JSON only."
    )


def _map_items(script: Script, stories: list[Story]) -> list[list[uuid.UUID]]:
    by_number = {s.number: s.item.id for s in stories}
    return [[by_number[n] for n in seg.item_ids if n in by_number] for seg in script.segments]


async def write_script(
    llm: LLMProvider,
    model: str,
    show: Show,
    speakers: list[SpeakerSpec],
    stories: list[Story],
    *,
    run_id: uuid.UUID | None = None,
) -> WrittenScript:
    """Ask the model for the script; if it is not usable, tell it what is wrong and ask once more.

    Missing stories, unknown speakers or empty segments after the second try raise
    `ScriptInvalid`; a script that is merely too long or too short is accepted with a warning.
    """
    metadata = CallMetadata(show_id=show.id, run_id=run_id, stage=STAGE)
    messages = [
        Message("system", SYSTEM_PROMPT),
        Message("user", render_prompt(show, speakers, stories)),
    ]
    numbers = [s.number for s in stories]
    target, _low, _high, _unit = length_targets(show.language, show.target_minutes)

    result = await llm.complete(
        messages, model=model, response_schema=Script, temperature=TEMPERATURE, metadata=metadata
    )
    assert isinstance(result.parsed, Script)
    script = result.parsed
    problems = check_script(script, speakers, numbers, show)
    regenerated = False
    if problems:
        log.info("script_regenerating", show_id=str(show.id), problems=problems.all)
        regenerated = True
        retry = await llm.complete(
            [*messages, Message("assistant", result.text), Message("user", _feedback(problems))],
            model=model,
            response_schema=Script,
            temperature=TEMPERATURE,
            metadata=metadata,
        )
        assert isinstance(retry.parsed, Script)
        script = retry.parsed
        problems = check_script(script, speakers, numbers, show)
        if problems.structural:
            raise ScriptInvalid(" ".join(problems.structural))
    units = sum(count_units(s.text, show.language) for s in script.segments)
    return WrittenScript(
        script=script,
        segment_item_ids=_map_items(script, stories),
        units=units,
        target_units=target,
        regenerated=regenerated,
        warnings=problems.length,
    )
