from byop.models.enums import CredentialProvider
from byop.providers.common import CallMetadata, RetryPolicy
from byop.providers.llm.base import (
    LLMError,
    LLMProvider,
    LLMResponseError,
    LLMResult,
    Message,
    ModelInfo,
    TokenUsage,
)
from byop.providers.llm.openai_compatible import OPENAI_BASE_URL, OpenAICompatibleLLM
from byop.providers.llm.openrouter import OpenRouterLLM
from byop.services.credentials import ProviderConfig

# Built-in providers that can serve chat completions (connections come on top of these).
LLM_PROVIDERS = (
    CredentialProvider.OPENROUTER,
    CredentialProvider.OPENAI,
)


class UnsupportedLLMProvider(ValueError):
    pass


def get_llm(
    provider: CredentialProvider,
    config: ProviderConfig,
    *,
    timeout_s: float = 120.0,
    retry: RetryPolicy | None = None,
) -> LLMProvider:
    """Build the LLM client for `provider` from resolved credentials."""
    key = config.api_key.get_secret_value() if config.api_key else None
    match provider:
        case CredentialProvider.OPENROUTER:
            if key is None:
                raise UnsupportedLLMProvider("OpenRouter needs an API key")
            if config.base_url:
                return OpenRouterLLM(
                    api_key=key, base_url=config.base_url, timeout_s=timeout_s, retry=retry
                )
            return OpenRouterLLM(api_key=key, timeout_s=timeout_s, retry=retry)
        case CredentialProvider.OPENAI:
            if key is None:
                raise UnsupportedLLMProvider("OpenAI needs an API key")
            return OpenAICompatibleLLM(
                base_url=config.base_url or OPENAI_BASE_URL,
                api_key=key,
                name="openai",
                timeout_s=timeout_s,
                retry=retry,
            )
        case CredentialProvider.OPENAI_COMPATIBLE:
            if not config.base_url:
                raise UnsupportedLLMProvider("An OpenAI-compatible provider needs a base URL")
            return OpenAICompatibleLLM(
                base_url=config.base_url,
                api_key=key,
                name=config.usage_name,
                headers=dict(config.headers),
                timeout_s=timeout_s,
                retry=retry,
            )
        case _:
            raise UnsupportedLLMProvider(f"'{provider.value}' is not an LLM provider")


__all__ = [
    "LLM_PROVIDERS",
    "CallMetadata",
    "LLMError",
    "LLMProvider",
    "LLMResponseError",
    "LLMResult",
    "Message",
    "ModelInfo",
    "OpenAICompatibleLLM",
    "OpenRouterLLM",
    "RetryPolicy",
    "TokenUsage",
    "UnsupportedLLMProvider",
    "get_llm",
]
