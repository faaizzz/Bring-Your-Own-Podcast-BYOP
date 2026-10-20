from typing import ClassVar

from byop.providers.common import RetryPolicy
from byop.providers.tts.base import ProviderQuirks, SpeechModel, Voice
from byop.providers.tts.openai_tts import OpenAITTS

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Speech models are not part of OpenRouter's default model list: they are asked for by output.
SPEECH_MODELS_PATH = "/models?output_modalities=speech"

# Offered only when OpenRouter lists no speech model at all (a failed call is an error instead).
FALLBACK_MODELS = (
    SpeechModel("hexgrad/kokoro-82m", "Kokoro 82M"),
    SpeechModel("elevenlabs/eleven-flash-v2.5", "ElevenLabs Flash v2.5"),
    SpeechModel("mistralai/voxtral-mini-tts-2603", "Mistral Voxtral Mini TTS"),
    SpeechModel("google/gemini-3.1-flash-tts-preview", "Gemini 3.1 Flash TTS (preview)"),
    SpeechModel("deepgram/aura-2", "Deepgram Aura 2"),
)


class OpenRouterTTS(OpenAITTS):
    """TTS models exposed through OpenRouter's OpenAI-compatible `/audio/speech`."""

    name = "openrouter"
    quirks: ClassVar[ProviderQuirks] = ProviderQuirks(
        max_chars_per_request=4096,
        formats=OpenAITTS.quirks.formats,
        default_format="pcm",
        supported_params=OpenAITTS.quirks.supported_params | {"model"},
        # There is no sensible default model: the caller must pick one OpenRouter offers.
        required_params=frozenset({"model"}),
        model_param="model",
        voices_follow_model=True,
        timeout_s=120.0,
        param_specs=OpenAITTS.quirks.param_specs,
    )
    default_model: ClassVar[str | None] = None

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = OPENROUTER_BASE_URL,
        timeout_s: float | None = None,
        retry: RetryPolicy | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            timeout_s=timeout_s,
            retry=retry,
            default_headers={"X-Title": "BYOP"},
        )

    async def list_models(self) -> list[SpeechModel]:
        """The models OpenRouter says produce speech, with the voices each one offers."""
        payload = await self._get_json(f"{self._base_url}{SPEECH_MODELS_PATH}", self.auth_headers())
        entries = payload.get("data") if isinstance(payload, dict) else None
        models: list[SpeechModel] = []
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                continue
            voices = entry.get("supported_voices")
            description = entry.get("description")
            models.append(
                SpeechModel(
                    id=entry["id"],
                    name=str(entry.get("name") or entry["id"]),
                    description=description if isinstance(description, str) else None,
                    voices=tuple(v for v in voices if isinstance(v, str))
                    if isinstance(voices, list)
                    else (),
                )
            )
        return models or list(FALLBACK_MODELS)

    async def list_voices(self, model: str | None = None) -> list[Voice]:
        """The voices of `model` as OpenRouter lists them; OpenAI's names when it lists none (or
        no model is chosen yet)."""
        if model:
            for candidate in await self.list_models():
                if candidate.id == model and candidate.voices:
                    return [Voice(id=v, name=v) for v in candidate.voices]
        return await super().list_voices(model)
