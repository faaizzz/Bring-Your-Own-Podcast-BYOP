from typing import ClassVar

from byop.providers.common import RetryPolicy
from byop.providers.tts.base import ParamSpec, ProviderQuirks, Voice
from byop.providers.tts.openai_tts import OpenAITTS

# Kokoro voice ids are `<language><gender>_<name>`, e.g. `af_bella` or `bm_george`.
_LANGUAGES = {
    "a": "en-US",
    "b": "en-GB",
    "e": "es",
    "f": "fr",
    "h": "hi",
    "i": "it",
    "j": "ja",
    "p": "pt-BR",
    "z": "zh",
}
_GENDERS = {"f": "female", "m": "male"}


def describe_voice(voice_id: str) -> Voice:
    """Decode a Kokoro voice id into a display name, language and gender."""
    prefix, _, name = voice_id.partition("_")
    if len(prefix) == 2 and prefix[0] in _LANGUAGES and prefix[1] in _GENDERS and name:
        return Voice(
            id=voice_id,
            name=name.replace("_", " ").title(),
            language=_LANGUAGES[prefix[0]],
            gender=_GENDERS[prefix[1]],
        )
    return Voice(id=voice_id, name=voice_id)


class KokoroTTS(OpenAITTS):
    """Local, free text-to-speech: a Kokoro-FastAPI server speaking the OpenAI speech API."""

    name: ClassVar[str] = "kokoro"
    quirks: ClassVar[ProviderQuirks] = ProviderQuirks(
        # On a CPU a request takes roughly as long as the text is long (about 0.15 s per
        # character), so chunks stay small enough to finish well within the timeout.
        max_chars_per_request=800,
        formats=OpenAITTS.quirks.formats,
        default_format="pcm",
        supported_params=frozenset({"speed", "lang_code", "volume_multiplier"}),
        # CPU synthesis is far slower than a hosted API.
        timeout_s=300.0,
        # The server works through requests one at a time, so parallel ones only wait in its
        # queue (and each one's wait counts against the timeout).
        max_concurrency=1,
        param_specs={
            "speed": ParamSpec("number", minimum=0.25, maximum=4.0),
            "lang_code": ParamSpec("string", max_length=8),
            "volume_multiplier": ParamSpec("number", minimum=0.0, maximum=4.0),
        },
    )
    default_model: ClassVar[str | None] = "kokoro"

    def __init__(
        self,
        *,
        base_url: str,
        timeout_s: float | None = None,
        retry: RetryPolicy | None = None,
    ) -> None:
        super().__init__(api_key="", base_url=base_url, timeout_s=timeout_s, retry=retry)

    def auth_headers(self) -> dict[str, str]:
        return {}  # a local server needs no key

    async def list_voices(self) -> list[Voice]:
        payload = await self._get_json(f"{self._base_url}/audio/voices", {})
        entries = payload.get("voices", []) if isinstance(payload, dict) else []
        # Kokoro-FastAPI lists voice objects (`{"id": "af_bella", ...}`); older builds plain names.
        names = [e.get("id") if isinstance(e, dict) else e for e in entries]
        return [describe_voice(name) for name in names if isinstance(name, str)]
