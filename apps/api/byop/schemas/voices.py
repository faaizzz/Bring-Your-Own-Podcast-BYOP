from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from byop.schemas.speaker import TTSProviderName, VoiceId, VoiceParams


class VoiceResponse(BaseModel):
    id: str
    name: str
    language: str | None = None
    gender: str | None = None
    preview_url: str | None = None


class SpeechModelResponse(BaseModel):
    id: str
    name: str
    description: str | None = None


class SpeechModelsResponse(BaseModel):
    """The speech models of a provider and how the speaker's settings name them."""

    # The voice parameter that holds the model ("model", "model_id"); null when there is no choice.
    param: str | None
    required: bool
    # What the provider uses when none is chosen; null when it has no default.
    default: str | None
    # Whether the voices on offer depend on the model (so choosing another one starts over).
    voices_follow_model: bool
    # Empty when the provider lists none: the model is then typed in.
    models: list[SpeechModelResponse]


class DefaultProviderResponse(BaseModel):
    # None when no TTS provider is usable (no paid key and no running Kokoro).
    provider: str | None


class VoicePreviewRequest(BaseModel):
    provider: TTSProviderName
    voice_id: VoiceId
    # The speaker's voice parameters (speed, stability, ...), validated per provider.
    params: VoiceParams = Field(default_factory=dict)
    # A short sample line; a default sentence is used when omitted.
    text: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
        | None
    ) = None
