import uuid
from decimal import Decimal

import httpx
import pytest
import respx
from pydantic import BaseModel

from byop.providers.common import UsageRecord, reset_usage_sink, set_usage_sink
from byop.providers.llm import (
    CallMetadata,
    LLMError,
    LLMResponseError,
    Message,
    OpenAICompatibleLLM,
    OpenRouterLLM,
    RetryPolicy,
)
from tests.providers.llm.helpers import FAST_RETRY, OPENROUTER_URL, body_of, completion

MESSAGES = [Message("system", "Be brief."), Message("user", "Say hi")]


class Greeting(BaseModel):
    greeting: str
    times: int = 1


def openrouter(retry: RetryPolicy = FAST_RETRY) -> OpenRouterLLM:
    return OpenRouterLLM(api_key="sk-or-test", retry=retry)


# --- plain completions -------------------------------------------------------------------


@respx.mock
async def test_plain_completion_returns_text_usage_and_latency() -> None:
    route = respx.post(OPENROUTER_URL).respond(200, json=completion("Hello!", model="vendor/x-1"))

    result = await openrouter().complete(
        MESSAGES, model="vendor/x", temperature=0.3, metadata=CallMetadata(stage="script")
    )

    assert result.text == "Hello!"
    assert result.parsed is None
    assert (result.usage.input_tokens, result.usage.output_tokens) == (10, 5)
    assert result.usage.total_tokens == 15
    assert result.raw_model == "vendor/x-1"
    assert result.latency_ms >= 0
    body = body_of(route)
    assert body["model"] == "vendor/x"
    assert body["temperature"] == 0.3
    assert body["messages"] == [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "Say hi"},
    ]
    assert "response_format" not in body


@respx.mock
async def test_openrouter_requests_and_returns_the_cost() -> None:
    route = respx.post(OPENROUTER_URL).respond(200, json=completion("ok", cost=0.000123))

    result = await openrouter().complete(MESSAGES, model="m")

    assert body_of(route)["usage"] == {"include": True}
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-or-test"
    assert result.cost_usd == Decimal("0.000123")
    assert isinstance(result.cost_usd, Decimal)


@respx.mock
async def test_missing_cost_is_none_not_zero() -> None:
    respx.post(OPENROUTER_URL).respond(200, json=completion("ok"))

    assert (await openrouter().complete(MESSAGES, model="m")).cost_usd is None


@respx.mock
async def test_openai_compatible_has_no_cost_and_uses_its_base_url() -> None:
    route = respx.post("http://host.docker.internal:11434/v1/chat/completions").respond(
        200, json=completion("hi", cost=9.9)
    )
    llm = OpenAICompatibleLLM(base_url="http://host.docker.internal:11434/v1", retry=FAST_RETRY)

    result = await llm.complete(MESSAGES, model="llama3.1")

    assert result.cost_usd is None  # only OpenRouter reports cost
    assert "usage" not in body_of(route)
    assert route.calls.last.request.headers["authorization"] == "Bearer not-needed"


@respx.mock
async def test_missing_usage_is_zero() -> None:
    payload = completion("ok")
    del payload["usage"]
    respx.post(OPENROUTER_URL).respond(200, json=payload)

    result = await openrouter().complete(MESSAGES, model="m")

    assert result.usage.total_tokens == 0


@respx.mock
async def test_empty_choices_is_an_error() -> None:
    respx.post(OPENROUTER_URL).respond(200, json={**completion("x"), "choices": []})

    with pytest.raises(LLMError, match="no choices"):
        await openrouter().complete(MESSAGES, model="m")


# --- structured output -------------------------------------------------------------------


@respx.mock
async def test_structured_output_sends_a_json_schema_and_parses_the_reply() -> None:
    route = respx.post(OPENROUTER_URL).respond(
        200, json=completion('{"greeting": "hi", "times": 2}')
    )

    result = await openrouter().complete(MESSAGES, model="m", response_schema=Greeting)

    assert result.parsed == Greeting(greeting="hi", times=2)
    assert isinstance(result.parsed, Greeting)
    fmt = body_of(route)["response_format"]
    assert isinstance(fmt, dict) and fmt["type"] == "json_schema"
    assert fmt["json_schema"]["name"] == "Greeting"
    assert fmt["json_schema"]["schema"]["properties"]["greeting"]["type"] == "string"


@respx.mock
@pytest.mark.parametrize(
    "reply",
    [
        '```json\n{"greeting": "hi"}\n```',
        'Sure thing! {"greeting": "hi"} Anything else?',
    ],
)
async def test_tolerant_extraction_avoids_a_repair_round(reply: str) -> None:
    route = respx.post(OPENROUTER_URL).respond(200, json=completion(reply))

    result = await openrouter().complete(MESSAGES, model="m", response_schema=Greeting)

    assert result.parsed == Greeting(greeting="hi")
    assert route.call_count == 1


@respx.mock
async def test_invalid_reply_gets_one_repair_retry_and_usage_is_summed() -> None:
    route = respx.post(OPENROUTER_URL).mock(
        side_effect=[
            httpx.Response(
                200, json=completion('{"greeting": 5, "times": "x"}', cost=0.001, prompt=10)
            ),
            httpx.Response(
                200,
                json=completion('{"greeting": "hi"}', cost=0.002, prompt=30, completion_tokens=7),
            ),
        ]
    )

    result = await openrouter().complete(MESSAGES, model="m", response_schema=Greeting)

    assert result.parsed == Greeting(greeting="hi")
    assert route.call_count == 2
    repair = body_of(route, 1)["messages"]
    assert isinstance(repair, list)
    assert repair[-2] == {"role": "assistant", "content": '{"greeting": 5, "times": "x"}'}
    assert "greeting" in str(repair[-1]["content"])  # tells the model what was wrong
    assert (result.usage.input_tokens, result.usage.output_tokens) == (40, 12)
    assert result.cost_usd == Decimal("0.003")


@respx.mock
async def test_still_invalid_after_repair_raises_with_a_clear_message() -> None:
    route = respx.post(OPENROUTER_URL).respond(200, json=completion("I refuse to use JSON"))

    with pytest.raises(LLMResponseError, match="Greeting.*after one repair"):
        await openrouter().complete(MESSAGES, model="m", response_schema=Greeting)

    assert route.call_count == 2  # original + exactly one repair


@respx.mock
async def test_provider_rejecting_response_format_falls_back_to_prompted_json() -> None:
    route = respx.post("http://local/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(400, json={"error": {"message": "response_format unsupported"}}),
            httpx.Response(200, json=completion('{"greeting": "hi"}')),
        ]
    )
    llm = OpenAICompatibleLLM(base_url="http://local/v1", retry=FAST_RETRY)

    result = await llm.complete(MESSAGES, model="m", response_schema=Greeting)

    assert result.parsed == Greeting(greeting="hi")
    retried = body_of(route, 1)
    assert "response_format" not in retried
    first_message = retried["messages"][0]  # type: ignore[index]
    assert first_message["role"] == "system" and "JSON Schema" in first_message["content"]


# --- retries -------------------------------------------------------------------------------


@respx.mock
async def test_429_is_retried_until_it_succeeds() -> None:
    route = respx.post(OPENROUTER_URL).mock(
        side_effect=[
            httpx.Response(429, json={"error": {"message": "slow down"}}),
            httpx.Response(429, json={"error": {"message": "slow down"}}),
            httpx.Response(200, json=completion("finally")),
        ]
    )

    result = await openrouter().complete(MESSAGES, model="m")

    assert result.text == "finally"
    assert route.call_count == 3


@respx.mock
async def test_5xx_is_retried() -> None:
    route = respx.post(OPENROUTER_URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json=completion("up again"))]
    )

    assert (await openrouter().complete(MESSAGES, model="m")).text == "up again"
    assert route.call_count == 2


@respx.mock
async def test_retries_stop_at_the_limit_and_report_the_status() -> None:
    route = respx.post(OPENROUTER_URL).respond(429, json={"error": {"message": "nope"}})

    with pytest.raises(LLMError, match="HTTP 429") as excinfo:
        await openrouter().complete(MESSAGES, model="m")

    assert excinfo.value.status_code == 429
    assert route.call_count == FAST_RETRY.max_attempts


@respx.mock
@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_client_errors_are_not_retried(status: int) -> None:
    route = respx.post(OPENROUTER_URL).respond(status, json={"error": {"message": "no"}})

    with pytest.raises(LLMError) as excinfo:
        await openrouter().complete(MESSAGES, model="m")

    assert excinfo.value.status_code == status
    assert route.call_count == 1


@respx.mock
async def test_retry_after_is_honoured_up_to_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []
    real_wait = OpenRouterLLM._wait

    def spy(self: OpenRouterLLM, state: object) -> float:
        value = real_wait(self, state)  # type: ignore[arg-type]
        waits.append(value)
        return 0.0  # do not actually sleep

    monkeypatch.setattr(OpenRouterLLM, "_wait", spy)
    respx.post(OPENROUTER_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "7"}),
            httpx.Response(200, json=completion("ok")),
        ]
    )
    llm = OpenRouterLLM(
        api_key="k", retry=RetryPolicy(max_attempts=2, initial_wait_s=1, max_wait_s=10)
    )

    await llm.complete(MESSAGES, model="m")

    assert waits == [7.0]


@respx.mock
async def test_network_errors_are_retried_then_reported() -> None:
    route = respx.post(OPENROUTER_URL).mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(LLMError, match="Could not reach openrouter"):
        await openrouter().complete(MESSAGES, model="m")

    assert route.call_count == FAST_RETRY.max_attempts


@respx.mock
async def test_timeouts_are_retried_then_reported() -> None:
    route = respx.post(OPENROUTER_URL).mock(side_effect=httpx.ReadTimeout("slow"))

    with pytest.raises(LLMError, match="timed out"):
        await openrouter().complete(MESSAGES, model="m")

    assert route.call_count == FAST_RETRY.max_attempts


@respx.mock
async def test_the_configured_timeout_reaches_the_http_client() -> None:
    respx.post(OPENROUTER_URL).respond(200, json=completion("ok"))
    llm = OpenRouterLLM(api_key="k", timeout_s=7.5, retry=FAST_RETRY)

    await llm.complete(MESSAGES, model="m")

    assert llm.client.timeout == 7.5


# --- metadata and logging --------------------------------------------------------------------


@respx.mock
async def test_metadata_is_logged_without_prompt_content(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from byop.logging import configure_logging

    configure_logging("INFO")
    respx.post(OPENROUTER_URL).respond(200, json=completion("secret reply", cost=0.5))
    run_id = uuid.uuid4()

    await openrouter().complete(
        [Message("user", "private prompt text")],
        model="m",
        metadata=CallMetadata(run_id=run_id, stage="script"),
    )

    out = capsys.readouterr().out
    assert str(run_id) in out and '"stage": "script"' in out
    assert "private prompt text" not in out and "secret reply" not in out


# --- model lists ----------------------------------------------------------------------------


@respx.mock
async def test_openrouter_model_list_with_prices_per_million_tokens() -> None:
    respx.get("https://openrouter.ai/api/v1/models").respond(
        200,
        json={
            "data": [
                {
                    "id": "anthropic/claude-x",
                    "name": "Claude X",
                    "context_length": 200000,
                    "pricing": {"prompt": "0.000003", "completion": "0.000015"},
                },
                {
                    "id": "openrouter/auto",
                    "name": "Auto",
                    "pricing": {"prompt": "-1", "completion": "-1"},
                },
                {"id": "free/model", "pricing": {"prompt": "0", "completion": "0"}},
                {"name": "no id, skipped"},
            ]
        },
    )

    models = await openrouter().list_models()

    claude, auto, free = models
    assert (claude.id, claude.name, claude.context_length) == (
        "anthropic/claude-x",
        "Claude X",
        200000,
    )
    assert claude.prompt_price_per_million == Decimal("3")
    assert claude.completion_price_per_million == Decimal("15")
    assert auto.prompt_price_per_million is None and auto.context_length is None
    assert free.name == "free/model" and free.prompt_price_per_million == Decimal("0")


@respx.mock
async def test_openai_compatible_model_list_has_ids_only() -> None:
    respx.get("http://local/v1/models").respond(
        200,
        json={
            "object": "list",
            "data": [{"id": "llama3.1", "object": "model", "created": 0, "owned_by": "x"}],
        },
    )

    models = await OpenAICompatibleLLM(base_url="http://local/v1", retry=FAST_RETRY).list_models()

    assert [(m.id, m.name, m.prompt_price_per_million) for m in models] == [
        ("llama3.1", "llama3.1", None)
    ]


# --- usage reporting -------------------------------------------------------------------------


class Collect:
    def __init__(self) -> None:
        self.records: list[UsageRecord] = []

    def record(self, usage: UsageRecord) -> None:
        self.records.append(usage)


@respx.mock
async def test_every_completion_reports_its_usage_to_the_active_sink() -> None:
    respx.post(OPENROUTER_URL).respond(
        200,
        json=completion(
            "Hello!", model="vendor/x-1", prompt=120, completion_tokens=30, cost="0.0007"
        ),
    )
    run_id, show_id = uuid.uuid4(), uuid.uuid4()
    sink = Collect()
    token = set_usage_sink(sink)
    try:
        await openrouter().complete(
            MESSAGES,
            model="vendor/x",
            metadata=CallMetadata(stage="script", run_id=run_id, show_id=show_id),
        )
    finally:
        reset_usage_sink(token)

    (usage,) = sink.records
    assert (usage.kind, usage.provider, usage.stage) == ("llm", "openrouter", "script")
    assert usage.model == "vendor/x-1"  # the model that actually answered
    assert (usage.input_tokens, usage.output_tokens) == (120, 30)
    assert usage.cost_usd == Decimal("0.0007")
    assert (usage.run_id, usage.show_id) == (run_id, show_id) and usage.latency_ms >= 0


@respx.mock
async def test_a_repaired_reply_is_one_call_with_the_tokens_of_every_request() -> None:
    respx.post(OPENROUTER_URL).mock(
        side_effect=[
            httpx.Response(200, json=completion("not json", prompt=10, completion_tokens=2)),
            httpx.Response(
                200, json=completion('{"greeting": "hi"}', prompt=20, completion_tokens=4)
            ),
        ]
    )
    sink = Collect()
    token = set_usage_sink(sink)
    try:
        await openrouter().complete(MESSAGES, model="m", response_schema=Greeting)
    finally:
        reset_usage_sink(token)

    (usage,) = sink.records
    assert (usage.input_tokens, usage.output_tokens) == (30, 6)


@respx.mock
async def test_a_failed_call_reports_nothing_and_no_sink_is_fine() -> None:
    respx.post(OPENROUTER_URL).respond(401, json={"error": {"message": "bad key"}})
    sink = Collect()
    token = set_usage_sink(sink)
    try:
        with pytest.raises(LLMError):
            await openrouter().complete(MESSAGES, model="m")
    finally:
        reset_usage_sink(token)
    assert sink.records == []

    respx.post(OPENROUTER_URL).respond(200, json=completion("ok"))
    await openrouter().complete(MESSAGES, model="m")  # no sink at all
