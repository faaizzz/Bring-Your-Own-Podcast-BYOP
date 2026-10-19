import uuid

import pytest
from pydantic import SecretStr

from byop.models.enums import CredentialProvider as P
from byop.providers.tts import (
    ElevenLabsTTS,
    KokoroTTS,
    OpenAICompatibleTTS,
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


@pytest.mark.parametrize("provider", [P.LANGFUSE])
def test_providers_without_a_tts_adapter_are_rejected(provider: P) -> None:
    with pytest.raises(UnsupportedTTSProvider, match="not a TTS provider"):
        get_tts(provider, config(provider))


def test_a_key_is_required() -> None:
    with pytest.raises(UnsupportedTTSProvider, match="API key"):
        get_tts(P.OPENAI, config(P.OPENAI, key=None))


def test_kokoro_needs_a_base_url_but_no_key() -> None:
    tts = get_tts(P.KOKORO, config(P.KOKORO, key=None, base_url="http://kokoro:8880/v1"))

    assert isinstance(tts, KokoroTTS)
    with pytest.raises(UnsupportedTTSProvider, match="base URL"):
        get_tts(P.KOKORO, config(P.KOKORO, key=None))


def test_a_connection_needs_a_base_url_but_not_a_key() -> None:
    cfg = ProviderConfig(
        P.OPENAI_COMPATIBLE,
        "user",
        None,
        "http://tts.local/v1",
        headers={"X-Gateway": "abc"},
        connection_id=uuid.uuid4(),
        label="Local TTS",
    )

    tts = get_tts(P.OPENAI_COMPATIBLE, cfg)

    assert isinstance(tts, OpenAICompatibleTTS)
    assert tts.name == "conn:Local TTS"
    assert tts.auth_headers() == {}
    with pytest.raises(UnsupportedTTSProvider, match="base URL"):
        get_tts(P.OPENAI_COMPATIBLE, config(P.OPENAI_COMPATIBLE, key=None))
