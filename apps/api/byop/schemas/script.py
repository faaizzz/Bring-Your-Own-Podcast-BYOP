from typing import Literal

from pydantic import BaseModel, Field

SegmentKind = Literal["intro", "story", "transition", "outro"]


class Segment(BaseModel):
    """One turn of speech."""

    speaker: str
    text: str
    kind: SegmentKind
    # For `story` segments: the numbers (as listed in the prompt) of the stories this turn covers.
    item_ids: list[int] = Field(default_factory=list)


class Script(BaseModel):
    """What the model writes: the episode's title and description and its spoken lines."""

    title: str
    description: str
    segments: list[Segment]
