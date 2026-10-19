from typing import Literal

from pydantic import BaseModel


class ProviderOption(BaseModel):
    """One choice in a provider picker: a built-in provider or one of the user's connections."""

    # What shows and speakers store: `openai`, `kokoro`, ..., or `conn:<id>`.
    id: str
    label: str
    kind: Literal["builtin", "connection"]
    # False when it cannot be used yet (no key saved, or the connection is disabled).
    configured: bool
    capabilities: list[Literal["llm", "tts", "web_search"]]
