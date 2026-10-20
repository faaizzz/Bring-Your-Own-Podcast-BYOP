from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, overload

from pydantic import BaseModel

from byop.providers.common import CallMetadata, Throttle


class LLMError(Exception):
    """A request to the model provider failed (after retries).

    `status_code`, `code` and `detail` are what the provider itself said (HTTP status, its error
    code and its message, already stripped of anything that looks like a key), so callers can
    explain the failure instead of guessing.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.detail = detail


class LLMResponseError(LLMError):
    """The model replied, but not with output matching the requested schema (even after repair)."""


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            self.input_tokens + other.input_tokens, self.output_tokens + other.output_tokens
        )


@dataclass(frozen=True)
class LLMResult[T: BaseModel]:
    text: str
    parsed: T | None
    usage: TokenUsage
    # Provider-reported cost in USD (OpenRouter); None when the provider does not say.
    cost_usd: Decimal | None
    latency_ms: int
    # The model that actually served the request (routers may pick a different one).
    raw_model: str | None


@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str
    context_length: int | None = None
    prompt_price_per_million: Decimal | None = None
    completion_price_per_million: Decimal | None = None
    # What the provider says the model accepts (OpenRouter: `supported_parameters`).
    supported_parameters: tuple[str, ...] = ()
    # What the model produces ("text", "image", ...); empty when the provider does not say.
    output_modalities: tuple[str, ...] = ()
    # True when the model searches the web by itself; None when the provider does not say.
    web_search: bool | None = None


class LLMProvider(ABC):
    name: str
    # Spaces out the requests when the user set a wait for this provider (see `get_llm`).
    throttle: Throttle | None = None

    @overload
    async def complete[T: BaseModel](
        self,
        messages: list[Message],
        *,
        model: str,
        response_schema: type[T],
        temperature: float | None = None,
        metadata: CallMetadata | None = None,
    ) -> LLMResult[T]: ...

    @overload
    async def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        response_schema: None = None,
        temperature: float | None = None,
        metadata: CallMetadata | None = None,
    ) -> LLMResult[BaseModel]: ...

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        response_schema: type[BaseModel] | None = None,
        temperature: float | None = None,
        metadata: CallMetadata | None = None,
    ) -> LLMResult[BaseModel]:
        """Run a chat completion; with `response_schema` the reply is validated into `parsed`."""

    @abstractmethod
    async def aclose(self) -> None:
        """Release network resources; providers are cheap to build, so close them after use."""

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """The models this provider offers."""
