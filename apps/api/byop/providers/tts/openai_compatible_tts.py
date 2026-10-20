from dataclasses import replace
from typing import ClassVar

from byop.providers.common import RetryPolicy
from byop.providers.tts.base import ParamSpec, ProviderQuirks, SpeechModel, Voice
from byop.providers.tts.errors import TTSError
from byop.providers.tts.kokoro_tts import describe_voice
from byop.providers.tts.openai_tts import OpenAITTS

# A server of the user's own: possibly local and slow, never known in advance.
_QUIRKS = replace(
    OpenAITTS.quirks,
    supported_params=OpenAITTS.quirks.supported_params | {"lang_code", "volume_multiplier"},
    param_specs={
        **OpenAITTS.quirks.param_specs,
        "lang_code": ParamSpec("string", max_length=8),
        "volume_multiplier": ParamSpec("number", minimum=0.0, maximum=4.0),
    },
    timeout_s=300.0,
)


class OpenAICompatibleTTS(OpenAITTS):
    """`POST /audio/speech` on a server of the user's own (a connection): Kokoro-FastAPI, a
    gateway, another OpenAI-compatible service. Its custom headers go with every request."""

    quirks: ClassVar[ProviderQuirks] = _QUIRKS
    default_model: ClassVar[str | None] = None

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        name: str = "openai_compatible",
        headers: dict[str, str] | None = None,
        timeout_s: float | None = None,
        retry: RetryPolicy | None = None,
    ) -> None:
        self.name = name
        self._extra_headers = dict(headers or {})
        super().__init__(
            api_key=api_key or "",
            base_url=base_url,
            timeout_s=timeout_s,
            retry=retry,
            default_headers=self._extra_headers,
        )

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

    async def list_models(self) -> list[SpeechModel]:
        """The server's `GET /models`, if it has one; a server without it (or a failing one)
        simply has no list, and the user types the model."""
        try:
            payload = await self._get_json(f"{self._base_url}/models", self.auth_headers())
        except TTSError:
            return []
        entries = payload.get("data") if isinstance(payload, dict) else None
        return [
            SpeechModel(id=entry["id"], name=entry["id"])
            for entry in (entries if isinstance(entries, list) else [])
            if isinstance(entry, dict) and isinstance(entry.get("id"), str)
        ]

    async def list_voices(self, model: str | None = None) -> list[Voice]:
        """The server's voice list (`GET /audio/voices`, as Kokoro-FastAPI offers it). Servers
        without one answer with an error; the caller then lets the user type a voice id."""
        payload = await self._get_json(f"{self._base_url}/audio/voices", self.auth_headers())
        entries = payload.get("voices") if isinstance(payload, dict) else payload
        names = [
            e.get("id") if isinstance(e, dict) else e
            for e in (entries if isinstance(entries, list) else [])
        ]
        return [describe_voice(name) for name in names if isinstance(name, str)]
