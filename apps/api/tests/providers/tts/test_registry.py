import pytest
from pydantic import SecretStr

from byop.models.enums import CredentialProvider as P
from byop.providers.tts import (
    ElevenLabsTTS,
    OpenAITTS,
    OpenRouterTTS,
    UnsupportedTTSProvider,
    get_tts,
)
from byop.services.credentials import ProviderConfig


def config(provider: P, key: str | None = "k", base_url: str | None = None) -> ProviderConfig:
    return ProviderConfig(provider, "env", SecretStr(key) if key else None, base_url)


def test_each_provider_maps_to_its_class() -> None:
    assert isinstance(get_tts(P.OPENAI, config(P.OPENAI)), OpenAITTS)
    assert isinstance(get_tts(P.ELEVENLABS, config(P.ELEVENLABS)), ElevenLabsTTS)
    assert isinstance(get_tts(P.OPENROUTER, config(P.OPENROUTER)), OpenRouterTTS)


def test_a_configured_base_url_is_used() -> None:
    tts = get_tts(P.OPENAI, config(P.OPENAI, base_url="https://proxy.example/v1"))

    assert tts._base_url == "https://proxy.example/v1"


@pytest.mark.parametrize("provider", [P.KOKORO, P.LANGFUSE, P.OPENAI_COMPATIBLE])
def test_providers_without_a_tts_adapter_are_rejected(provider: P) -> None:
    with pytest.raises(UnsupportedTTSProvider, match="not a TTS provider"):
        get_tts(provider, config(provider))


def test_a_key_is_required() -> None:
    with pytest.raises(UnsupportedTTSProvider, match="API key"):
        get_tts(P.OPENAI, config(P.OPENAI, key=None))
