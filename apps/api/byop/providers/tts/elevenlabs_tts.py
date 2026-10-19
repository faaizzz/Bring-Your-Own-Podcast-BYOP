from collections.abc import Mapping
from typing import ClassVar
from urllib.parse import quote

from byop.providers.common import RetryPolicy
from byop.providers.tts.audio import AudioFormat
from byop.providers.tts.base import AudioRequest, ParamSpec, ProviderQuirks, TTSProvider, Voice

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"
DEFAULT_MODEL = "eleven_multilingual_v2"

# Passed to the API inside `voice_settings`; every other supported param is a top-level field.
_VOICE_SETTINGS = ("stability", "similarity_boost", "style", "speed", "use_speaker_boost")
_TOP_LEVEL = ("language_code", "seed")

_FORMATS = {
    "pcm": AudioFormat("pcm", "pcm", "pcm_24000", pcm_rate=24000),
    "mp3": AudioFormat("mp3", "mp3", "mp3_44100_128"),
}


class ElevenLabsTTS(TTSProvider):
    """ElevenLabs' native `POST /v1/text-to-speech/{voice_id}`."""

    name = "elevenlabs"
    quirks: ClassVar[ProviderQuirks] = ProviderQuirks(
        # eleven_multilingual_v2's limit; the Flash/Turbo models accept more.
        max_chars_per_request=5000,
        formats=_FORMATS,
        default_format="pcm",
        supported_params=frozenset({"model_id", *_VOICE_SETTINGS, *_TOP_LEVEL}),
        timeout_s=120.0,
        param_specs={
            "model_id": ParamSpec("string", max_length=100),
            "stability": ParamSpec("number", minimum=0.0, maximum=1.0),
            "similarity_boost": ParamSpec("number", minimum=0.0, maximum=1.0),
            "style": ParamSpec("number", minimum=0.0, maximum=1.0),
            "speed": ParamSpec("number", minimum=0.7, maximum=1.2),
            "use_speaker_boost": ParamSpec("boolean"),
            "language_code": ParamSpec("string", max_length=16),
            "seed": ParamSpec("integer", minimum=0, maximum=4294967295),
        },
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = ELEVENLABS_BASE_URL,
        timeout_s: float | None = None,
        retry: RetryPolicy | None = None,
    ) -> None:
        super().__init__(api_key=api_key, base_url=base_url, timeout_s=timeout_s, retry=retry)

    def build_request(
        self, text: str, voice_id: str, params: Mapping[str, object], audio_format: AudioFormat
    ) -> AudioRequest:
        payload: dict[str, object] = {
            "text": text,
            "model_id": params.get("model_id", DEFAULT_MODEL),
        }
        settings = {key: params[key] for key in _VOICE_SETTINGS if key in params}
        if settings:
            payload["voice_settings"] = settings
        for key in _TOP_LEVEL:
            if key in params:
                payload[key] = params[key]
        return AudioRequest(
            url=f"{self._base_url}/text-to-speech/{quote(voice_id, safe='')}",
            json=payload,
            headers={"xi-api-key": self._api_key},
            query={"output_format": audio_format.api_value},
        )

    async def list_voices(self) -> list[Voice]:
        payload = await self._get_json(f"{self._base_url}/voices", {"xi-api-key": self._api_key})
        entries = payload.get("voices", []) if isinstance(payload, dict) else []
        voices: list[Voice] = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("voice_id"), str):
                continue
            labels = entry.get("labels")
            labels = labels if isinstance(labels, dict) else {}
            verified = entry.get("verified_languages")
            first = verified[0] if isinstance(verified, list) and verified else {}
            language = labels.get("language") or (
                first.get("language") if isinstance(first, dict) else None
            )
            voices.append(
                Voice(
                    id=entry["voice_id"],
                    name=str(entry.get("name") or entry["voice_id"]),
                    language=str(language) if language else None,
                    gender=str(labels["gender"]) if labels.get("gender") else None,
                    preview_url=entry.get("preview_url")
                    if isinstance(entry.get("preview_url"), str)
                    else None,
                )
            )
        return voices
