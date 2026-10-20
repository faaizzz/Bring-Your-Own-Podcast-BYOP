import re
import uuid
from datetime import datetime, time
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, Field, StringConstraints, model_validator

from byop.models.enums import RunStatus, ScheduleKind, ShowStyle
from byop.services.provider_ref import check_llm_ref

# A built-in provider (`openrouter`, `openai`) or a connection (`conn:<id>`).
LLMProviderName = Annotated[str, AfterValidator(check_llm_ref)]

# Primary language subtag plus up to three further subtags: en, en-US, zh-Hans-CN, es-419.
_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8}){0,3}$")
_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _check_language(value: str) -> str:
    if not _LANGUAGE.fullmatch(value):
        raise ValueError("must be a BCP-47 language tag such as 'en' or 'pt-BR'")
    return value


def _check_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ValueError("must be an IANA time zone such as 'Europe/Berlin'") from exc
    return value


def _check_slug(value: str) -> str:
    if not _SLUG.fullmatch(value):
        raise ValueError("may only contain lowercase letters, digits and single hyphens")
    return value


def _check_email(value: str) -> str:
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        raise ValueError("must be an email address")
    return value


Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Topic = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]
Language = Annotated[str, AfterValidator(_check_language)]
Timezone = Annotated[str, AfterValidator(_check_timezone)]
Slug = Annotated[str, StringConstraints(max_length=100), AfterValidator(_check_slug)]
TargetMinutes = Annotated[int, Field(ge=1, le=60)]
ItemsPerEpisode = Annotated[int, Field(ge=1, le=20)]
Weekday = Annotated[int, Field(ge=0, le=6)]  # 0 = Monday
Monthday = Annotated[int, Field(ge=1, le=31)]
RankingHints = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
ModelName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Email = Annotated[str, StringConstraints(max_length=320), AfterValidator(_check_email)]

# Fields that may be cleared with an explicit null; everything else must keep a value.
NULLABLE_FIELDS = frozenset(
    {
        "custom_style_id",
        "prompt_override",
        "ranking_hints",
        "llm_provider",
        "llm_model",
        "schedule_time",
        "schedule_weekday",
        "schedule_monthday",
        "feed_author",
        "feed_email",
        "feed_category",
    }
)


def schedule_problem(
    kind: ScheduleKind, at: time | None, weekday: int | None, monthday: int | None
) -> str | None:
    """Why a schedule is incomplete, or None when it is usable."""
    if kind is ScheduleKind.MANUAL:
        return None
    if at is None:
        return f"A {kind.value} schedule needs a time of day"
    if kind is ScheduleKind.WEEKLY and weekday is None:
        return "A weekly schedule needs a weekday"
    if kind is ScheduleKind.MONTHLY and monthday is None:
        return "A monthly schedule needs a day of the month"
    return None


class ShowCreate(BaseModel):
    title: Title
    topic: Topic
    # Generated from the title when omitted.
    slug: Slug | None = None
    description: Description = ""
    language: Language = "en"
    target_minutes: TargetMinutes = 10
    # None selects the instance default (see DEFAULT_SHOW_STYLE / DEFAULT_LLM_*).
    style: ShowStyle | None = None
    # One of the user's own styles, instead of a built-in `style`.
    custom_style_id: uuid.UUID | None = None
    prompt_override: Annotated[str, StringConstraints(max_length=20000)] | None = None
    ranking_hints: RankingHints | None = None
    llm_provider: LLMProviderName | None = None
    llm_model: ModelName | None = None
    items_per_episode: ItemsPerEpisode = 5

    schedule_kind: ScheduleKind = ScheduleKind.MANUAL
    schedule_time: time | None = None
    schedule_weekday: Weekday | None = None
    schedule_monthday: Monthday | None = None
    timezone: Timezone = "UTC"
    paused: bool = False
    auto_publish: bool = False

    feed_author: Annotated[str, StringConstraints(max_length=200)] | None = None
    feed_email: Email | None = None
    feed_category: Annotated[str, StringConstraints(max_length=100)] | None = None
    feed_explicit: bool = False
    feed_enabled: bool = True

    @model_validator(mode="after")
    def _one_style(self) -> "ShowCreate":
        if self.style is not None and self.custom_style_id is not None:
            raise ValueError("Choose either a built-in style or one of your own, not both")
        return self

    @model_validator(mode="after")
    def _complete_schedule(self) -> "ShowCreate":
        problem = schedule_problem(
            self.schedule_kind, self.schedule_time, self.schedule_weekday, self.schedule_monthday
        )
        if problem:
            raise ValueError(problem)
        return self


class ShowUpdate(BaseModel):
    """Partial update: only the fields present in the request change."""

    title: Title | None = None
    slug: Slug | None = None
    topic: Topic | None = None
    description: Description | None = None
    language: Language | None = None
    target_minutes: TargetMinutes | None = None
    style: ShowStyle | None = None
    # Set to switch to one of the user's styles; null (or choosing a built-in `style`) goes back
    # to a built-in.
    custom_style_id: uuid.UUID | None = None
    prompt_override: Annotated[str, StringConstraints(max_length=20000)] | None = None
    ranking_hints: RankingHints | None = None
    llm_provider: LLMProviderName | None = None
    llm_model: ModelName | None = None
    items_per_episode: ItemsPerEpisode | None = None

    schedule_kind: ScheduleKind | None = None
    schedule_time: time | None = None
    schedule_weekday: Weekday | None = None
    schedule_monthday: Monthday | None = None
    timezone: Timezone | None = None
    paused: bool | None = None
    auto_publish: bool | None = None

    feed_author: Annotated[str, StringConstraints(max_length=200)] | None = None
    feed_email: Email | None = None
    feed_category: Annotated[str, StringConstraints(max_length=100)] | None = None
    feed_explicit: bool | None = None
    feed_enabled: bool | None = None

    @model_validator(mode="after")
    def _one_style(self) -> "ShowUpdate":
        if self.style is not None and self.custom_style_id is not None:
            raise ValueError("Choose either a built-in style or one of your own, not both")
        return self

    @model_validator(mode="after")
    def _only_optional_fields_may_be_null(self) -> "ShowUpdate":
        for name in self.model_fields_set - NULLABLE_FIELDS:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class ShowResponse(BaseModel):
    id: uuid.UUID
    title: str
    slug: str
    # True once an episode has been published: the feed URL must stay stable from then on.
    slug_locked: bool
    topic: str
    description: str
    language: str
    target_minutes: int
    style: ShowStyle
    # Set when the show uses one of the user's own styles (then `style` is not used).
    custom_style_id: uuid.UUID | None
    prompt_override: str | None
    ranking_hints: str | None
    llm_provider: str | None
    llm_model: str | None
    items_per_episode: int

    schedule_kind: ScheduleKind
    schedule_time: time | None
    schedule_weekday: int | None
    schedule_monthday: int | None
    timezone: str
    paused: bool
    auto_publish: bool
    next_run_at: datetime | None

    feed_author: str | None
    feed_email: str | None
    feed_category: str | None
    feed_explicit: bool
    feed_enabled: bool
    # Absolute address of the public RSS feed (from PUBLIC_BASE_URL).
    feed_url: str

    # Public, versioned URL of the cover image; None until one is uploaded.
    cover_url: str | None
    # Versioned URLs (for the signed-in owner) of the show's intro, outro and music bed clips.
    intro_url: str | None
    outro_url: str | None
    music_url: str | None
    episode_count: int
    last_run_status: RunStatus | None
    # When the newest episode was published (or created, for a draft).
    last_episode_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Non-blocking notes from the last create/update, e.g. a model that could not be verified.
    warnings: list[str] = Field(default_factory=list)
