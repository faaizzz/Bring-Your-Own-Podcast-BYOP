from collections.abc import Mapping
from typing import ClassVar

from byop.providers.common import RetryPolicy
from byop.providers.tts.audio import AudioFormat
from byop.providers.tts.base import AudioRequest, ProviderQuirks, TTSProvider, Voice

OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini-tts"

# The API has no voice listing endpoint, so the built-in voices are listed here.
OPENAI_VOICES = (
    "alloy", "ash", "ballad", "cedar", "coral", "echo", "fable", "marin", "nova", "onyx",
    "sage", "shimmer", "verse",
)  # fmt: skip

_FORMATS = {
    # Raw 24 kHz signed 16-bit mono: needs only a WAV header.
    "pcm": AudioFormat("pcm", "pcm", "pcm", pcm_rate=24000),
    "mp3": AudioFormat("mp3", "mp3", "mp3"),
}


class OpenAITTS(TTSProvider):
    """`POST /audio/speech` (OpenAI, or any server that implements the same endpoint)."""

    name: ClassVar[str] = "openai"
    quirks: ClassVar[ProviderQuirks] = ProviderQuirks(
        max_chars_per_request=4096,
        formats=_FORMATS,
        default_format="pcm",
        supported_params=frozenset({"model", "speed", "instructions"}),
        timeout_s=120.0,
    )
    default_model: ClassVar[str | None] = DEFAULT_MODEL

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = OPENAI_BASE_URL,
        timeout_s: float | None = None,
        retry: RetryPolicy | None = None,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            timeout_s=timeout_s,
            retry=retry,
            default_headers=default_headers,
        )

    def build_request(
        self, text: str, voice_id: str, params: Mapping[str, object], audio_format: AudioFormat
    ) -> AudioRequest:
        payload: dict[str, object] = {
            "model": params.get("model", self.default_model),
            "input": text,
            "voice": voice_id,
            "response_format": audio_format.api_value,
        }
        # Params were validated against `quirks.supported_params`, so forward every extra one.
        payload.update({k: v for k, v in params.items() if k not in {"model", "format"}})
        return AudioRequest(
            url=f"{self._base_url}/audio/speech",
            json=payload,
            headers=self.auth_headers(),
        )

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def list_voices(self) -> list[Voice]:
        return [Voice(id=voice, name=voice.capitalize()) for voice in OPENAI_VOICES]
