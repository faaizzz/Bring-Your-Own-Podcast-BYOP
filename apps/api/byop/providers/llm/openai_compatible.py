from byop.providers.common import RetryPolicy
from byop.providers.llm.openai_chat import OpenAIChatProvider

OPENAI_BASE_URL = "https://api.openai.com/v1"
# Local servers (Ollama, LM Studio) ignore the key, but the SDK insists on one.
PLACEHOLDER_KEY = "not-needed"


class OpenAICompatibleLLM(OpenAIChatProvider):
    """OpenAI itself, or anything exposing the same API: Ollama, LM Studio, vLLM, proxies."""

    def __init__(
        self,
        *,
        base_url: str = OPENAI_BASE_URL,
        api_key: str | None = None,
        name: str = "openai_compatible",
        timeout_s: float = 120.0,
        retry: RetryPolicy | None = None,
    ) -> None:
        self.name = name
        super().__init__(
            api_key=api_key or PLACEHOLDER_KEY,
            base_url=base_url,
            timeout_s=timeout_s,
            retry=retry,
        )
