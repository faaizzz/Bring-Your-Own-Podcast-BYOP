"""How a show or speaker names its provider: a built-in provider, or one of the user's connections.

The reference is stored as text in `Show.llm_provider`, `Speaker.tts_provider` and
`Speaker.fallback_tts_provider`: `openrouter`, `openai`, `elevenlabs`, `kokoro`, or
`conn:<connection id>`.
"""

import uuid
from dataclasses import dataclass

from byop.models.enums import CredentialProvider

CONNECTION_PREFIX = "conn:"

# Built-in providers a reference may name (a connection takes the place of the old
# `openai_compatible` credential, and Langfuse is not a model provider).
BUILTIN_REFS = tuple(
    p for p in CredentialProvider if p not in {CredentialProvider.OPENAI_COMPATIBLE}
)


# Built-in providers that can serve each use.
LLM_BUILTINS = (CredentialProvider.OPENROUTER, CredentialProvider.OPENAI)
TTS_BUILTINS = (
    CredentialProvider.OPENAI,
    CredentialProvider.ELEVENLABS,
    CredentialProvider.OPENROUTER,
    CredentialProvider.KOKORO,
)


class InvalidProviderRef(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderRef:
    builtin: CredentialProvider | None = None
    connection_id: uuid.UUID | None = None

    @classmethod
    def parse(cls, raw: str) -> "ProviderRef":
        if raw.startswith(CONNECTION_PREFIX):
            try:
                return cls(connection_id=uuid.UUID(raw[len(CONNECTION_PREFIX) :]))
            except ValueError as exc:
                raise InvalidProviderRef(f"'{raw}' is not a valid connection reference") from exc
        try:
            provider = CredentialProvider(raw)
        except ValueError as exc:
            raise InvalidProviderRef(f"Unknown provider '{raw}'") from exc
        if provider not in BUILTIN_REFS:
            raise InvalidProviderRef(f"Unknown provider '{raw}'")
        return cls(builtin=provider)

    @classmethod
    def of(cls, provider: CredentialProvider) -> "ProviderRef":
        return cls(builtin=provider)

    @property
    def kind(self) -> CredentialProvider:
        """The provider family: a connection is always an OpenAI-compatible server."""
        return self.builtin or CredentialProvider.OPENAI_COMPATIBLE

    @property
    def is_connection(self) -> bool:
        return self.connection_id is not None

    def __str__(self) -> str:
        if self.connection_id is not None:
            return f"{CONNECTION_PREFIX}{self.connection_id}"
        assert self.builtin is not None
        return self.builtin.value


def _check(value: str, allowed: tuple[CredentialProvider, ...], use: str) -> str:
    try:
        ref = ProviderRef.parse(value)
    except InvalidProviderRef as exc:
        raise ValueError(str(exc)) from exc
    if ref.builtin is not None and ref.builtin not in allowed:
        raise ValueError(f"'{value}' cannot be used for {use}")
    return str(ref)


def check_llm_ref(value: str) -> str:
    """Validator for a stored language-model provider reference (shape only)."""
    return _check(value, LLM_BUILTINS, "language models")


def check_tts_ref(value: str) -> str:
    """Validator for a stored voice provider reference (shape only)."""
    return _check(value, TTS_BUILTINS, "voices")
