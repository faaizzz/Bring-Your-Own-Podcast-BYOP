"""Shared implementation for providers that speak the OpenAI chat-completions protocol."""

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
import openai
import structlog
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion
from pydantic import BaseModel, ValidationError
from tenacity import AsyncRetrying, RetryCallState, retry_if_exception, stop_after_attempt

from byop.providers.common import (
    CallMetadata,
    RetryPolicy,
    UsageRecord,
    backoff_seconds,
    record_usage,
)
from byop.providers.llm.base import (
    LLMError,
    LLMProvider,
    LLMResponseError,
    LLMResult,
    Message,
    ModelInfo,
    TokenUsage,
)
from byop.providers.llm.json_extract import extract_json

log = structlog.get_logger(__name__)

MAX_ERRORS_IN_REPAIR_PROMPT = 5


@dataclass
class _Totals:
    """Usage and cost summed over every request one `complete()` call makes."""

    usage: TokenUsage = field(default_factory=TokenUsage)
    cost: Decimal | None = None
    raw_model: str | None = None
    requests: int = 0

    def add(self, completion: ChatCompletion, *, with_cost: bool) -> None:
        self.requests += 1
        self.raw_model = completion.model or self.raw_model
        usage = completion.usage
        if usage is None:
            return
        self.usage += TokenUsage(usage.prompt_tokens, usage.completion_tokens)
        if with_cost:
            cost = _decimal((usage.model_extra or {}).get("cost"))
            if cost is not None:
                self.cost = (self.cost or Decimal(0)) + cost


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, openai.RateLimitError | openai.APIConnectionError):  # incl. timeouts
        return True
    return isinstance(exc, openai.APIStatusError) and exc.status_code >= 500


def _json_schema_format(schema: type[BaseModel]) -> dict[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema.__name__[:64],
            "schema": schema.model_json_schema(),
            # Not strict: strict mode rejects ordinary pydantic schemas (defaults, optionals).
            # The reply is validated and repaired below instead.
            "strict": False,
        },
    }


def _schema_instructions(schema: type[BaseModel]) -> Message:
    return Message(
        "system",
        "Reply with a single JSON document that matches this JSON Schema, and nothing else:\n"
        + json.dumps(schema.model_json_schema()),
    )


def _describe(error: ValueError) -> str:
    if isinstance(error, ValidationError):
        parts = [
            f"{'.'.join(str(p) for p in e['loc']) or 'reply'}: {e['msg']}"
            for e in error.errors()[:MAX_ERRORS_IN_REPAIR_PROMPT]
        ]
        return "; ".join(parts)
    return str(error)


class OpenAIChatProvider(LLMProvider):
    # Whether the provider reports a per-request `usage.cost` (OpenRouter does).
    reports_cost = False

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_s: float = 120.0,
        retry: RetryPolicy | None = None,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        self._retry = retry or RetryPolicy()
        # The SDK's own retries are disabled; ours add jitter, Retry-After and a clear policy.
        # An explicit httpx client pins the HTTP stack: the SDK defaults to httpx2, which would
        # bypass the httpx transport mocks the tests rely on.
        self._http = httpx.AsyncClient(timeout=timeout_s)
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_s,
            max_retries=0,
            default_headers=default_headers,
            http_client=self._http,  # type: ignore[arg-type]  # plain httpx is supported at runtime
        )

    # -- request plumbing ---------------------------------------------------------------

    def _extra_body(self) -> dict[str, object] | None:
        return None

    def _wait(self, state: RetryCallState) -> float:
        exc = state.outcome.exception() if state.outcome else None
        retry_after = None
        if isinstance(exc, openai.APIStatusError):
            retry_after = exc.response.headers.get("retry-after")
        return backoff_seconds(self._retry, state.attempt_number, retry_after)

    async def _chat(
        self,
        *,
        model: str,
        messages: list[Message],
        temperature: float | None,
        response_format: dict[str, object] | None,
        totals: _Totals,
    ) -> str:
        params: dict[str, object] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if temperature is not None:
            params["temperature"] = temperature
        if response_format is not None:
            params["response_format"] = response_format
        extra_body = self._extra_body()
        if extra_body:
            params["extra_body"] = extra_body

        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._retry.max_attempts),
            wait=self._wait,
            retry=retry_if_exception(is_retryable),
            reraise=True,
        )

        async def attempt() -> ChatCompletion:
            # A plain coroutine function: tenacity only awaits callables it recognises as async.
            call_kwargs: Any = params  # assembled dynamically; the SDK validates them at runtime
            return await self.client.chat.completions.create(**call_kwargs)  # type: ignore[no-any-return]

        try:
            completion: ChatCompletion = await retrying(attempt)
        except openai.APITimeoutError as exc:
            raise LLMError(f"{self.name} request timed out") from exc
        except openai.APIConnectionError as exc:
            raise LLMError(f"Could not reach {self.name}") from exc
        except openai.APIStatusError as exc:
            raise LLMError(
                f"{self.name} request failed (HTTP {exc.status_code})", status_code=exc.status_code
            ) from exc

        totals.add(completion, with_cost=self.reports_cost)
        if not completion.choices:
            raise LLMError(f"{self.name} returned no choices")
        return completion.choices[0].message.content or ""

    # -- public API ---------------------------------------------------------------------

    async def complete(  # type: ignore[override]  # overloads live on the base class
        self,
        messages: list[Message],
        *,
        model: str,
        response_schema: type[BaseModel] | None = None,
        temperature: float | None = None,
        metadata: CallMetadata | None = None,
    ) -> LLMResult[BaseModel]:
        started = time.perf_counter()
        started_at = datetime.now(UTC)
        totals = _Totals()
        parsed: BaseModel | None = None

        if response_schema is None:
            text = await self._chat(
                model=model,
                messages=messages,
                temperature=temperature,
                response_format=None,
                totals=totals,
            )
        else:
            text, parsed = await self._structured(
                messages, model, response_schema, temperature, totals
            )

        latency_ms = int((time.perf_counter() - started) * 1000)
        meta = metadata or CallMetadata()
        log.info(
            "llm_complete",
            provider=self.name,
            model=model,
            raw_model=totals.raw_model,
            stage=meta.stage,
            run_id=str(meta.run_id) if meta.run_id else None,
            show_id=str(meta.show_id) if meta.show_id else None,
            input_tokens=totals.usage.input_tokens,
            output_tokens=totals.usage.output_tokens,
            cost_usd=str(totals.cost) if totals.cost is not None else None,
            requests=totals.requests,
            latency_ms=latency_ms,
        )
        record_usage(
            UsageRecord(
                kind="llm",
                provider=self.name,
                model=totals.raw_model or model,
                stage=meta.stage,
                run_id=meta.run_id,
                show_id=meta.show_id,
                latency_ms=latency_ms,
                input_tokens=totals.usage.input_tokens,
                output_tokens=totals.usage.output_tokens,
                cost_usd=totals.cost,
                started_at=started_at,
                prompt=json.dumps([{"role": m.role, "content": m.content} for m in messages]),
                completion=text,
                tags=dict(meta.tags),
            )
        )
        return LLMResult(
            text=text,
            parsed=parsed,
            usage=totals.usage,
            cost_usd=totals.cost,
            latency_ms=latency_ms,
            raw_model=totals.raw_model,
        )

    async def _structured(
        self,
        messages: list[Message],
        model: str,
        schema: type[BaseModel],
        temperature: float | None,
        totals: _Totals,
    ) -> tuple[str, BaseModel]:
        conversation = list(messages)
        response_format: dict[str, object] | None = _json_schema_format(schema)

        async def ask() -> str:
            return await self._chat(
                model=model,
                messages=conversation,
                temperature=temperature,
                response_format=response_format,
                totals=totals,
            )

        try:
            text = await ask()
        except LLMError as exc:
            if exc.status_code != 400:
                raise
            # The provider rejected `response_format`: ask for JSON in the prompt instead.
            response_format = None
            conversation.insert(0, _schema_instructions(schema))
            text = await ask()

        try:
            return text, _parse(text, schema)
        except ValueError as first_error:
            # One repair attempt: show the model its reply and what was wrong with it.
            conversation += [
                Message("assistant", text),
                Message(
                    "user",
                    f"Your previous reply could not be used ({_describe(first_error)}). "
                    "Reply again with only the corrected JSON document that matches the schema.",
                ),
            ]
            repaired = await ask()
            try:
                return repaired, _parse(repaired, schema)
            except ValueError as second_error:
                raise LLMResponseError(
                    f"{self.name} did not return valid {schema.__name__} output after one "
                    f"repair attempt ({_describe(second_error)})"
                ) from second_error

    async def aclose(self) -> None:
        await self._http.aclose()

    async def list_models(self) -> list[ModelInfo]:
        page = await self.client.models.list()
        return [ModelInfo(id=m.id, name=m.id) async for m in page]


def _parse(text: str, schema: type[BaseModel]) -> BaseModel:
    return schema.model_validate(extract_json(text))
