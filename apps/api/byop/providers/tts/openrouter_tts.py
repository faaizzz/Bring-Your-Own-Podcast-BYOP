from typing import ClassVar

from byop.providers.common import RetryPolicy
from byop.providers.tts.base import ProviderQuirks
from byop.providers.tts.openai_tts import OpenAITTS

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


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
