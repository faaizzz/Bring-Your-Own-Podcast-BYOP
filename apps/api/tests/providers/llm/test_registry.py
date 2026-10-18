import pytest
from pydantic import SecretStr

from byop.models.enums import CredentialProvider as P
from byop.providers.llm import (
    LLMProvider,
    OpenAICompatibleLLM,
    OpenRouterLLM,
    UnsupportedLLMProvider,
    get_llm,
)
from byop.services.credentials import ProviderConfig


def base_url_of(llm: LLMProvider) -> str:
    assert isinstance(llm, OpenAICompatibleLLM | OpenRouterLLM)
    return str(llm.client.base_url)


def config(provider: P, key: str | None = "sk-key", base_url: str | None = None) -> ProviderConfig:
    return ProviderConfig(provider, "env", SecretStr(key) if key else None, base_url)


def test_openrouter() -> None:
    llm = get_llm(P.OPENROUTER, config(P.OPENROUTER))

    assert isinstance(llm, OpenRouterLLM) and llm.name == "openrouter"
    assert base_url_of(llm).startswith("https://openrouter.ai/api/v1")


def test_openai_defaults_to_the_openai_endpoint_and_accepts_a_proxy() -> None:
    default = get_llm(P.OPENAI, config(P.OPENAI))
    proxied = get_llm(P.OPENAI, config(P.OPENAI, base_url="https://proxy.example/v1"))

    assert isinstance(default, OpenAICompatibleLLM) and default.name == "openai"
    assert base_url_of(default).startswith("https://api.openai.com/v1")
    assert base_url_of(proxied).startswith("https://proxy.example/v1")


def test_openai_compatible_needs_a_base_url_but_not_a_key() -> None:
    llm = get_llm(P.OPENAI_COMPATIBLE, config(P.OPENAI_COMPATIBLE, None, "http://ollama:11434/v1"))

    assert isinstance(llm, OpenAICompatibleLLM) and llm.name == "openai_compatible"
    with pytest.raises(UnsupportedLLMProvider, match="base URL"):
        get_llm(P.OPENAI_COMPATIBLE, config(P.OPENAI_COMPATIBLE, None, None))


@pytest.mark.parametrize("provider", [P.OPENROUTER, P.OPENAI])
def test_keyed_providers_need_a_key(provider: P) -> None:
    with pytest.raises(UnsupportedLLMProvider, match="API key"):
        get_llm(provider, config(provider, None))


@pytest.mark.parametrize("provider", [P.ELEVENLABS, P.LANGFUSE, P.KOKORO])
def test_non_llm_providers_are_rejected(provider: P) -> None:
    with pytest.raises(UnsupportedLLMProvider, match="not an LLM provider"):
        get_llm(provider, config(provider))
