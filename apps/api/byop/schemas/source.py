import uuid
from datetime import datetime
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, StringConstraints, model_validator

from byop.models.enums import SourceKind, SourceOrigin

Name = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Value = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048)]
MAX_QUERY_LENGTH = 500


def check_value(kind: SourceKind, value: str) -> str:
    """URLs for feeds and pages, free text (at most 500 characters) for a search query."""
    if kind is SourceKind.WEB_SEARCH:
        if len(value) > MAX_QUERY_LENGTH:
            raise ValueError(f"A search query is at most {MAX_QUERY_LENGTH} characters")
        return value
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc or " " in value:
        raise ValueError("Enter a full URL starting with http:// or https://")
    return value


class SourceCreate(BaseModel):
    kind: SourceKind
    value: Value
    name: Name | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def _value_matches_kind(self) -> "SourceCreate":
        self.value = check_value(self.kind, self.value)
        return self


class SourceUpdate(BaseModel):
    """The kind cannot change; to switch, delete the source and add another."""

    value: Value | None = None
    name: Name | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def _no_null_value_or_enabled(self) -> "SourceUpdate":
        for field in ("value", "enabled"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class SourceResponse(BaseModel):
    id: uuid.UUID
    show_id: uuid.UUID
    kind: SourceKind
    value: str
    name: str | None
    origin: SourceOrigin
    enabled: bool
    last_fetched_at: datetime | None
    last_error: str | None
    created_at: datetime


class SourceValidateRequest(BaseModel):
    kind: SourceKind
    value: Value


class SourceValidation(BaseModel):
    """The outcome of checking a source. A bad feed is an answer, not an HTTP error."""

    ok: bool
    title: str | None = None
    entry_count: int = 0
    latest_titles: list[str] = Field(default_factory=list)
    detail: str | None = None
