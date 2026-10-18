from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from byop.schemas.speaker import TTSProviderName, VoiceId, VoiceParams


class VoiceResponse(BaseModel):
    id: str
    name: str
    language: str | None = None
    gender: str | None = None
    preview_url: str | None = None


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
