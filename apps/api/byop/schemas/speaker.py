import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

TTSProviderName = Literal["openai", "elevenlabs", "openrouter", "kokoro"]

# Voice parameters are small scalars (speed, stability, a model name, ...).
type ParamValue = str | int | float | bool
VoiceParams = Annotated[dict[str, ParamValue], Field(max_length=20)]

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
VoiceId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
MAX_SPEAKERS = 4


class SpeakerIn(BaseModel):
    name: Name
    # Role and speaking style, passed to the script writer.
    persona: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
    tts_provider: TTSProviderName
    voice_id: VoiceId
    voice_params: VoiceParams = Field(default_factory=dict)
    fallback_tts_provider: TTSProviderName | None = None
    fallback_voice_id: VoiceId | None = None


class SpeakerResponse(BaseModel):
    id: uuid.UUID
    position: int
    name: str
    persona: str
    tts_provider: str
    voice_id: str
    voice_params: VoiceParams
    fallback_tts_provider: str | None
    fallback_voice_id: str | None


SpeakerList = Annotated[list[SpeakerIn], Field(min_length=1, max_length=MAX_SPEAKERS)]
