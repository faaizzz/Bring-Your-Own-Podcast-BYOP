import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Instructions = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)
]


class StyleCreate(BaseModel):
    name: Name
    description: Description = ""
    instructions: Instructions


class StyleUpdate(BaseModel):
    """Omitted fields keep their value."""

    name: Name | None = None
    description: Description | None = None
    instructions: Instructions | None = None


class StyleResponse(BaseModel):
    """A built-in style (read-only, `id` is its key such as `conversational`) or one of the
    user's own (`id` is a UUID)."""

    id: str
    kind: Literal["builtin", "custom"]
    name: str
    description: str
    instructions: str
    # Shows that use it; built-ins are counted too.
    shows_using: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class StyleId(BaseModel):
    id: uuid.UUID
