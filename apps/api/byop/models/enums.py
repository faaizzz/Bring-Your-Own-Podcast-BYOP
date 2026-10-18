import enum

from sqlalchemy import Enum


class ShowStyle(enum.StrEnum):
    NEWS_BRIEFING = "news_briefing"
    CONVERSATIONAL = "conversational"
    DEEP_DIVE = "deep_dive"
    INTERVIEW = "interview"


class ScheduleKind(enum.StrEnum):
    MANUAL = "manual"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class SourceKind(enum.StrEnum):
    RSS = "rss"
    URL = "url"
    WEB_SEARCH = "web_search"


class SourceOrigin(enum.StrEnum):
    DISCOVERED = "discovered"
    USER = "user"


class RunTrigger(enum.StrEnum):
    MANUAL = "manual"
    SCHEDULE = "schedule"
    RESYNTH = "resynth"  # voice and mix an edited draft again


class RunStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EventLevel(enum.StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class EpisodeStatus(enum.StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    REJECTED = "rejected"


class UsageKind(enum.StrEnum):
    LLM = "llm"
    TTS = "tts"


class CostSource(enum.StrEnum):
    PROVIDER = "provider"
    PRICE_TABLE = "price_table"
    UNKNOWN = "unknown"


class CredentialProvider(enum.StrEnum):
    OPENROUTER = "openrouter"
    OPENAI = "openai"
    ELEVENLABS = "elevenlabs"
    LANGFUSE = "langfuse"
    KOKORO = "kokoro"
    OPENAI_COMPATIBLE = "openai_compatible"


def enum_type(enum_cls: type[enum.StrEnum], name: str) -> Enum:
    """A VARCHAR column restricted by a CHECK constraint (easy to extend, unlike PG enums)."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )
