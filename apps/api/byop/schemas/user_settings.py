from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from byop.schemas.discovery import DiscoveryModel
from byop.schemas.show import LLMProviderName


class DiscoveryModelUpdate(BaseModel):
    provider: LLMProviderName
    model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class DiscoveryModelSetting(BaseModel):
    """The model saved in Settings and the one discovery would use now."""

    # Null when nothing is saved; discovery then falls back to .env, the show, the default.
    provider: str | None = None
    model: str | None = None
    # Null when no model is set up anywhere.
    effective: DiscoveryModel | None = None
    # Caveats that do not stop saving, e.g. that web search could not be confirmed.
    warnings: list[str] = Field(default_factory=list)
