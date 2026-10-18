from byop.models.enums import CredentialProvider
from byop.providers.common import CallMetadata, RetryPolicy
from byop.providers.tts.audio import CANONICAL_SAMPLE_RATE, AudioFormat
from byop.providers.tts.base import (
    CANONICAL_FORMAT,
    ProviderQuirks,
    TTSProvider,
    TTSResult,
    Voice,
)
from byop.providers.tts.elevenlabs_tts import ElevenLabsTTS
from byop.providers.tts.errors import AudioConversionError, TTSError, TTSParamError
from byop.providers.tts.kokoro_tts import KokoroTTS
from byop.providers.tts.openai_tts import OPENAI_BASE_URL, OpenAITTS
from byop.providers.tts.openrouter_tts import OpenRouterTTS
from byop.services.credentials import ProviderConfig

# Credential providers that can synthesize speech through this interface.
TTS_PROVIDERS = (
    CredentialProvider.OPENAI,
    CredentialProvider.ELEVENLABS,
    CredentialProvider.OPENROUTER,
    CredentialProvider.KOKORO,
)


class UnsupportedTTSProvider(ValueError):
    pass


def get_tts(
    provider: CredentialProvider,
    config: ProviderConfig,
    *,
    timeout_s: float | None = None,
    retry: RetryPolicy | None = None,
) -> TTSProvider:
    """Build the TTS client for `provider` from resolved credentials."""
    if provider not in TTS_PROVIDERS:
        raise UnsupportedTTSProvider(f"'{provider.value}' is not a TTS provider")
    if provider is CredentialProvider.KOKORO:
        if not config.base_url:
            raise UnsupportedTTSProvider("Kokoro needs a base URL")
        return KokoroTTS(base_url=config.base_url, timeout_s=timeout_s, retry=retry)
    if config.api_key is None:
        raise UnsupportedTTSProvider(f"{provider.value} needs an API key")
    key = config.api_key.get_secret_value()
    options: dict[str, object] = {"api_key": key, "timeout_s": timeout_s, "retry": retry}
    if config.base_url:
        options["base_url"] = config.base_url
    match provider:
        case CredentialProvider.OPENAI:
            return OpenAITTS(**options)  # type: ignore[arg-type]  # options match the signature
        case CredentialProvider.ELEVENLABS:
            return ElevenLabsTTS(**options)  # type: ignore[arg-type]
        case _:
            return OpenRouterTTS(**options)  # type: ignore[arg-type]


__all__ = [
    "CANONICAL_FORMAT",
    "CANONICAL_SAMPLE_RATE",
    "OPENAI_BASE_URL",
    "TTS_PROVIDERS",
    "AudioConversionError",
    "AudioFormat",
    "CallMetadata",
    "ElevenLabsTTS",
    "KokoroTTS",
    "OpenAITTS",
    "OpenRouterTTS",
    "ProviderQuirks",
    "RetryPolicy",
    "TTSError",
    "TTSParamError",
    "TTSProvider",
    "TTSResult",
    "UnsupportedTTSProvider",
    "Voice",
    "get_tts",
]
