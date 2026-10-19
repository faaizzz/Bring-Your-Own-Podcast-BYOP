from collections.abc import Mapping

from byop.models.enums import CredentialProvider
from byop.providers.common import CallMetadata, RetryPolicy
from byop.providers.tts.audio import CANONICAL_SAMPLE_RATE, AudioFormat, wav_to_mp3
from byop.providers.tts.base import (
    CANONICAL_FORMAT,
    ParamSpec,
    ProviderQuirks,
    TTSProvider,
    TTSResult,
    Voice,
)
from byop.providers.tts.elevenlabs_tts import ElevenLabsTTS
from byop.providers.tts.errors import AudioConversionError, TTSError, TTSParamError
from byop.providers.tts.kokoro_tts import KokoroTTS
from byop.providers.tts.openai_compatible_tts import OpenAICompatibleTTS
from byop.providers.tts.openai_tts import OPENAI_BASE_URL, OpenAITTS
from byop.providers.tts.openrouter_tts import OpenRouterTTS
from byop.services.credentials import ProviderConfig

# Credential providers that can synthesize speech through this interface.
TTS_PROVIDERS = (
    CredentialProvider.OPENAI,
    CredentialProvider.ELEVENLABS,
    CredentialProvider.OPENROUTER,
    CredentialProvider.KOKORO,
    CredentialProvider.OPENAI_COMPATIBLE,
)


class UnsupportedTTSProvider(ValueError):
    pass


_CLASSES: dict[CredentialProvider, type[TTSProvider]] = {
    CredentialProvider.OPENAI: OpenAITTS,
    CredentialProvider.ELEVENLABS: ElevenLabsTTS,
    CredentialProvider.OPENROUTER: OpenRouterTTS,
    CredentialProvider.KOKORO: KokoroTTS,
    CredentialProvider.OPENAI_COMPATIBLE: OpenAICompatibleTTS,
}


def quirks_for(provider: CredentialProvider) -> ProviderQuirks:
    """The declared limits and parameters of a TTS provider, without creating a client."""
    if provider not in _CLASSES:
        raise UnsupportedTTSProvider(f"'{provider.value}' is not a TTS provider")
    return _CLASSES[provider].quirks


def voice_param_problems(
    provider: CredentialProvider, params: Mapping[str, object]
) -> dict[str, str]:
    """Parameter name -> problem for a speaker's `voice_params` (empty when they are fine).

    Checks names, required ones, and types/bounds from the provider's `ProviderQuirks`
    without creating a client. `format` is chosen by the pipeline, never by a speaker.
    """
    quirks = quirks_for(provider)
    problems: dict[str, str] = {}
    for key in sorted(set(params) - quirks.supported_params):
        problems[key] = "is not supported by this provider"
    for key in sorted(quirks.required_params - set(params)):
        problems[key] = "is required for this provider"
    supported = {k: v for k, v in params.items() if k in quirks.supported_params}
    problems.update(quirks.value_problems(supported))
    return problems


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
    if provider is CredentialProvider.OPENAI_COMPATIBLE:
        if not config.base_url:
            raise UnsupportedTTSProvider("An OpenAI-compatible connection needs a base URL")
        return OpenAICompatibleTTS(
            base_url=config.base_url,
            api_key=config.api_key.get_secret_value() if config.api_key else None,
            name=config.usage_name,
            headers=dict(config.headers),
            timeout_s=timeout_s,
            retry=retry,
        )
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
    "OpenAICompatibleTTS",
    "OpenAITTS",
    "OpenRouterTTS",
    "ParamSpec",
    "ProviderQuirks",
    "RetryPolicy",
    "TTSError",
    "TTSParamError",
    "TTSProvider",
    "TTSResult",
    "UnsupportedTTSProvider",
    "quirks_for",
    "voice_param_problems",
    "wav_to_mp3",
    "Voice",
    "get_tts",
]
