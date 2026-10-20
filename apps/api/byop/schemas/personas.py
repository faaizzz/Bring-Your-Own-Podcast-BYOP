import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from byop.schemas.speaker import Name, TTSProviderName, VoiceId, VoiceParams

PersonaText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]


class PersonaIn(BaseModel):
    name: Name
    persona: PersonaText
    # The default voice: a provider and a voice together, or neither.
    tts_provider: TTSProviderName | None = None
    voice_id: VoiceId | None = None
    voice_params: VoiceParams = Field(default_factory=dict)

    @model_validator(mode="after")
    def _voice_is_complete(self) -> "PersonaIn":
        if (self.tts_provider is None) != (self.voice_id is None):
            raise ValueError("A default voice needs both a provider and a voice")
        if self.tts_provider is None and self.voice_params:
            raise ValueError("Voice settings need a default voice")
        return self


class PersonaUpdate(BaseModel):
    """Omitted fields keep their value; `tts_provider` and `voice_id` set to null remove the
    default voice."""

    name: Name | None = None
    persona: PersonaText | None = None
    tts_provider: TTSProviderName | None = None
    voice_id: VoiceId | None = None
    voice_params: VoiceParams | None = None


class PersonaResponse(BaseModel):
    id: uuid.UUID
    name: str
    persona: str
    tts_provider: str | None
    voice_id: str | None
    voice_params: VoiceParams
    created_at: datetime
    updated_at: datetime
