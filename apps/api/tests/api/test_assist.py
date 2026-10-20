import json
import time
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings, get_settings
from byop.models import Persona, Style, UsageEvent, User
from byop.services.user_settings import save_request_interval
from tests.helpers import make_settings
from tests.models.factories import make_connection
from tests.providers.llm.helpers import OPENROUTER_URL, body_of, completion

STYLE = "/api/assist/style"
PERSONA = "/api/assist/persona"

STYLE_JSON = {
    "name": "Late-night radio",
    "description": "Slow, warm and a little sleepy.",
    "instructions": "Open like a late-night radio host. Tell each story slowly, with pauses.",
}
PERSONA_JSON = {
    "name": "Night owl",
    "persona": "The night owl. Quiet and warm; speaks slowly and loves a small detail.",
}


def configured(**extra: object) -> Settings:
    return make_settings(
        openrouter_api_key=SecretStr("sk-or-test-key-123456"),
        default_llm_provider="openrouter",
        default_llm_model="vendor/model",
        **extra,
    )


@pytest.fixture(autouse=True)
def _settings(app: FastAPI) -> None:
    app.dependency_overrides[get_settings] = lambda: configured()


def reply(payload: object, **kwargs: Any) -> httpx.Response:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return httpx.Response(200, json=completion(text, **kwargs))


def prompt_of(route: respx.Route, call: int = -1) -> str:
    messages = body_of(route, call)["messages"]
    assert isinstance(messages, list)
    return str(messages[-1]["content"])


# --- a style --------------------------------------------------------------------------------


@respx.mock
async def test_a_brief_becomes_a_style_draft_and_nothing_is_saved(
    authed: AsyncClient, db_session: AsyncSession
) -> None:
    route = respx.post(OPENROUTER_URL).mock(return_value=reply(STYLE_JSON))

    response = await authed.post(
        STYLE, json={"brief": "A calm show for people who cannot sleep", "language": "de"}
    )

    assert response.status_code == 200
    assert response.json() == STYLE_JSON
    assert (await db_session.scalars(select(Style))).all() == []
    prompt = prompt_of(route)
    assert "A calm show for people who cannot sleep" in prompt
    assert "German" in prompt  # the name and description are written in the show's language
    # One built-in style's instructions are the example of the form.
    assert "friends talking about what happened this week" in prompt
    assert body_of(route)["model"] == "vendor/model"  # the instance default


@respx.mock
async def test_the_requested_model_is_used(authed: AsyncClient) -> None:
    route = respx.post(OPENROUTER_URL).mock(return_value=reply(STYLE_JSON))

    await authed.post(
        STYLE, json={"brief": "x", "provider": "openrouter", "model": "anthropic/other"}
    )

    assert body_of(route)["model"] == "anthropic/other"


@respx.mock
async def test_a_connection_can_design_too(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    conn = await make_connection(db_session, admin_user, "Home Ollama")
    route = respx.post("http://llm.local/v1/chat/completions").mock(
        return_value=reply(PERSONA_JSON)
    )

    response = await authed.post(
        PERSONA, json={"brief": "x", "provider": f"conn:{conn.id}", "model": "llama3"}
    )

    assert response.status_code == 200 and route.call_count == 1


@respx.mock
async def test_a_style_whose_instructions_could_not_be_saved_later_is_refused(
    authed: AsyncClient,
) -> None:
    broken = {**STYLE_JSON, "instructions": "Talk about {{ nothing_like_this }}."}
    respx.post(OPENROUTER_URL).mock(return_value=reply(broken))

    response = await authed.post(STYLE, json={"brief": "x"})

    assert response.status_code == 502
    assert "cannot be used" in response.json()["detail"]


# --- a persona ------------------------------------------------------------------------------


@respx.mock
async def test_a_brief_becomes_a_persona_draft_and_nothing_is_saved(
    authed: AsyncClient, db_session: AsyncSession
) -> None:
    route = respx.post(OPENROUTER_URL).mock(return_value=reply(PERSONA_JSON))

    response = await authed.post(PERSONA, json={"brief": "a night owl who speaks slowly"})

    assert response.status_code == 200 and response.json() == PERSONA_JSON
    assert (await db_session.scalars(select(Persona))).all() == []
    prompt = prompt_of(route)
    assert "a night owl who speaks slowly" in prompt and "English" in prompt
    assert "friendly sceptic" in prompt  # the examples of the form


# --- usage and cost --------------------------------------------------------------------------


@respx.mock
async def test_the_cost_is_recorded_without_a_run_or_a_show_and_shows_on_the_costs_page(
    authed: AsyncClient, db_session: AsyncSession
) -> None:
    respx.post(OPENROUTER_URL).mock(return_value=reply(STYLE_JSON, cost="0.0042"))

    await authed.post(STYLE, json={"brief": "x"})

    [event] = (await db_session.scalars(select(UsageEvent))).all()
    assert (event.stage, event.run_id, event.show_id) == ("assist", None, None)
    assert (event.provider, str(event.cost_usd)) == ("openrouter", "0.004200")
    by_stage = (await authed.get("/api/costs/summary", params={"group_by": "stage"})).json()
    [row] = [g for g in by_stage["groups"] if g["key"] == "assist"]
    assert row["cost_usd"] == "0.004200" and row["calls"] == 1
    assert by_stage["total"]["cost_usd"] == "0.004200"


# --- the answer is checked, and repaired once -----------------------------------------------


@respx.mock
async def test_a_reply_that_is_not_json_is_repaired_once(authed: AsyncClient) -> None:
    route = respx.post(OPENROUTER_URL).mock(
        side_effect=[reply("Sure! Here is a style for you."), reply(STYLE_JSON)]
    )

    response = await authed.post(STYLE, json={"brief": "x"})

    assert response.status_code == 200 and response.json() == STYLE_JSON
    assert route.call_count == 2
    assert "could not be used" in prompt_of(route)  # the model was told what was wrong


@respx.mock
async def test_a_draft_that_breaks_the_limits_is_repaired_once(authed: AsyncClient) -> None:
    too_long = {**PERSONA_JSON, "persona": "x" * 2001}
    route = respx.post(OPENROUTER_URL).mock(side_effect=[reply(too_long), reply(PERSONA_JSON)])

    response = await authed.post(PERSONA, json={"brief": "x"})

    assert response.status_code == 200 and response.json() == PERSONA_JSON
    assert route.call_count == 2


@respx.mock
async def test_a_reply_that_stays_unusable_is_a_clear_error(authed: AsyncClient) -> None:
    route = respx.post(OPENROUTER_URL).mock(return_value=reply("no json here"))

    response = await authed.post(STYLE, json={"brief": "x"})

    assert response.status_code == 502
    assert "did not return a usable style draft" in response.json()["detail"]
    assert route.call_count == 2  # asked again once, not forever


# --- errors ----------------------------------------------------------------------------------


async def test_without_a_model_the_error_says_how_to_fix_it(
    app: FastAPI, authed: AsyncClient
) -> None:
    app.dependency_overrides[get_settings] = lambda: make_settings()

    response = await authed.post(STYLE, json={"brief": "x"})

    assert response.status_code == 422
    assert "DEFAULT_LLM_PROVIDER" in response.json()["detail"]
    assert "choose a model" in response.json()["detail"].lower()


async def test_a_provider_that_is_not_set_up_is_a_422_that_says_so(
    app: FastAPI, authed: AsyncClient
) -> None:
    app.dependency_overrides[get_settings] = lambda: make_settings()

    response = await authed.post(
        STYLE, json={"brief": "x", "provider": "openai", "model": "gpt-4o"}
    )

    assert response.status_code == 422
    assert "openai" in response.json()["detail"] and "Integrations" in response.json()["detail"]


@respx.mock
@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, {"error": {"message": "No auth credentials found"}}, "rejected the API key"),
        (402, {"error": {"message": "Insufficient credits"}}, "credits or quota"),
        (404, {"error": {"message": "No endpoints found for x"}}, "does not know the model"),
        (429, {"error": {"message": "slow down please"}}, "rate limiting"),
    ],
)
async def test_a_provider_error_comes_back_in_its_own_words(
    authed: AsyncClient, status: int, body: dict[str, object], expected: str
) -> None:
    respx.post(OPENROUTER_URL).respond(status, json=body)

    response = await authed.post(PERSONA, json={"brief": "x"})

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert expected in detail and "OpenRouter" in detail and "The provider said:" in detail


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"brief": ""},
        {"brief": "  "},
        {"brief": "x" * 2001},
        {"brief": "x", "provider": "openrouter"},  # a provider needs its model
        {"brief": "x", "model": "m"},
        {"brief": "x", "provider": "nope", "model": "m"},
        {"brief": "x", "language": "x" * 17},
    ],
)
async def test_the_request_is_checked(authed: AsyncClient, body: dict[str, object]) -> None:
    assert (await authed.post(STYLE, json=body)).status_code == 422
    assert (await authed.post(PERSONA, json=body)).status_code == 422


async def test_requires_a_session(client: AsyncClient) -> None:
    assert (await client.post(STYLE, json={"brief": "x"})).status_code == 401
    assert (await client.post(PERSONA, json={"brief": "x"})).status_code == 401


# --- the wait between requests and the trace ------------------------------------------------


@respx.mock
async def test_the_providers_wait_between_requests_applies(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    respx.post(OPENROUTER_URL).mock(return_value=reply(PERSONA_JSON))
    await save_request_interval(db_session, admin_user.id, "openrouter", 0.5)
    await authed.post(PERSONA, json={"brief": "x"})  # the first goes straight through

    began = time.monotonic()
    await authed.post(PERSONA, json={"brief": "x"})

    assert time.monotonic() - began >= 0.4


@respx.mock
async def test_the_call_is_traced_in_langfuse_when_it_is_set_up(
    app: FastAPI, authed: AsyncClient
) -> None:
    host = "https://langfuse.test"
    app.dependency_overrides[get_settings] = lambda: configured(
        langfuse_public_key=SecretStr("pk-lf-test"),
        langfuse_secret_key=SecretStr("sk-lf-test"),
        langfuse_host=host,
    )
    respx.post(OPENROUTER_URL).mock(return_value=reply(STYLE_JSON))
    ingest = respx.post(f"{host}/api/public/ingestion").respond(
        207, json={"successes": [], "errors": []}
    )

    assert (await authed.post(STYLE, json={"brief": "x"})).status_code == 200

    events = [e for call in ingest.calls for e in json.loads(call.request.content)["batch"]]
    traces = [e["body"] for e in events if e["type"] == "trace-create" and "name" in e["body"]]
    generations = [e["body"] for e in events if e["type"] == "generation-create"]
    assert [t["name"] for t in traces] == ["Assist: style"]
    assert traces[0]["sessionId"] is None and traces[0]["tags"] == ["assist"]
    [generation] = generations
    assert generation["traceId"] == traces[0]["id"] and generation["model"] == "test/model"
    assert "x" in generation["input"]
    assert {e["body"]["traceId"] for e in events if "traceId" in e["body"]} == {traces[0]["id"]}


@respx.mock
async def test_without_langfuse_nothing_is_sent(authed: AsyncClient) -> None:
    respx.post(OPENROUTER_URL).mock(return_value=reply(STYLE_JSON))

    assert (await authed.post(STYLE, json={"brief": "x"})).status_code == 200
    # respx would have failed the test on any other, unmocked request.
