"""Shows, speakers, pickers and lists that refer to a connection (`conn:<id>`)."""

import logging
import uuid

import httpx
import pytest
import respx
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import get_settings
from byop.models import User
from tests.helpers import make_settings
from tests.models.factories import make_connection, make_user

HEADER = ("X-Gateway-Token", "gateway-token-abcdef123456")
KEY = "sk-conn-secret-0123456789"
MODELS = "http://llm.local/v1/models"
VOICES = "http://tts.local/v1/audio/voices"


@pytest.fixture
async def llm_conn(db_session: AsyncSession, admin_user: User) -> str:
    record = await make_connection(
        db_session, admin_user, "Ollama", api_key=KEY, headers=dict([HEADER])
    )
    return f"conn:{record.id}"


@pytest.fixture
async def tts_conn(db_session: AsyncSession, admin_user: User) -> str:
    record = await make_connection(
        db_session,
        admin_user,
        "Kokoro 2",
        base_url="http://tts.local/v1",
        headers=dict([HEADER]),
        llm=False,
        tts=True,
    )
    return f"conn:{record.id}"


# --- /api/providers -----------------------------------------------------------------------------


async def test_pickers_offer_built_in_providers_and_matching_connections(
    app: FastAPI, authed: AsyncClient, llm_conn: str, tts_conn: str, db_session: AsyncSession,
    admin_user: User,
) -> None:  # fmt: skip
    app.dependency_overrides[get_settings] = lambda: make_settings(
        openai_api_key=SecretStr("sk-env-key-0123456789")
    )
    await make_connection(db_session, admin_user, "Off", enabled=False)

    llm = (await authed.get("/api/providers", params={"capability": "llm"})).json()
    tts = (await authed.get("/api/providers", params={"capability": "tts"})).json()

    assert [(o["id"], o["configured"]) for o in llm if o["kind"] == "builtin"] == [
        ("openrouter", False),
        ("openai", True),
    ]
    assert [(o["label"], o["configured"]) for o in llm if o["kind"] == "connection"] == [
        ("Off", False),
        ("Ollama", True),
    ]  # the voice-only connection is not offered for models
    assert {o["id"] for o in tts if o["kind"] == "builtin"} == {
        "openrouter", "openai", "elevenlabs", "kokoro",
    }  # fmt: skip
    [voices] = [o for o in tts if o["kind"] == "connection"]
    assert (voices["id"], voices["label"], voices["capabilities"]) == (
        tts_conn,
        "Kokoro 2",
        ["tts"],
    )


async def test_the_capability_is_required(authed: AsyncClient) -> None:
    assert (await authed.get("/api/providers")).status_code == 422
    assert (await authed.get("/api/providers", params={"capability": "web"})).status_code == 422


# --- models and voices --------------------------------------------------------------------------


@respx.mock
async def test_models_of_a_connection_are_listed_with_its_headers(
    authed: AsyncClient, llm_conn: str
) -> None:
    route = respx.get(MODELS).respond(200, json={"data": [{"id": "llama3", "object": "model"}]})

    response = await authed.get("/api/models", params={"provider": llm_conn})

    assert [m["id"] for m in response.json()] == ["llama3"]
    sent = route.calls.last.request.headers
    assert sent[HEADER[0]] == HEADER[1] and sent["authorization"] == f"Bearer {KEY}"


@respx.mock
async def test_models_of_an_endpoint_without_a_list_route_are_a_bad_gateway(
    authed: AsyncClient, llm_conn: str
) -> None:
    respx.get(MODELS).respond(404)

    response = await authed.get("/api/models", params={"provider": llm_conn})

    assert response.status_code == 502  # the picker then lets the user type the model


@respx.mock
async def test_voices_of_a_connection_are_listed_with_its_headers(
    authed: AsyncClient, tts_conn: str
) -> None:
    route = respx.get(VOICES).respond(
        200, json={"voices": [{"id": "af_bella"}, "am_michael", {"name": "no id"}]}
    )

    response = await authed.get("/api/voices", params={"provider": tts_conn})

    assert [v["id"] for v in response.json()] == ["af_bella", "am_michael"]
    assert route.calls.last.request.headers[HEADER[0]] == HEADER[1]


@respx.mock
async def test_a_connection_that_cannot_list_voices_is_a_bad_gateway(
    authed: AsyncClient, tts_conn: str
) -> None:
    respx.get(VOICES).respond(404)

    assert (await authed.get("/api/voices", params={"provider": tts_conn})).status_code == 502


async def test_a_connection_not_enabled_for_the_use_is_a_conflict(
    authed: AsyncClient, llm_conn: str, tts_conn: str
) -> None:
    assert (await authed.get("/api/voices", params={"provider": llm_conn})).status_code == 409
    assert (await authed.get("/api/models", params={"provider": tts_conn})).status_code == 409
    gone = f"conn:{uuid.uuid4()}"
    assert (await authed.get("/api/models", params={"provider": gone})).status_code == 409


async def test_connections_of_other_users_cannot_be_used(
    authed: AsyncClient, db_session: AsyncSession
) -> None:
    other = await make_user(db_session, "other@example.com")
    theirs = await make_connection(db_session, other, "Theirs")

    response = await authed.get("/api/models", params={"provider": f"conn:{theirs.id}"})

    assert response.status_code == 409


@pytest.mark.parametrize("provider", ["conn:not-a-uuid", "conn:", "openai_compatible", "nope"])
async def test_malformed_references_are_rejected(authed: AsyncClient, provider: str) -> None:
    assert (await authed.get("/api/models", params={"provider": provider})).status_code == 422


# --- shows --------------------------------------------------------------------------------------


@respx.mock
async def test_a_show_can_use_a_connection_for_its_model(
    authed: AsyncClient, llm_conn: str
) -> None:
    respx.get(MODELS).respond(200, json={"data": [{"id": "llama3", "object": "model"}]})

    created = await authed.post(
        "/api/shows",
        json={"title": "Local", "topic": "t", "llm_provider": llm_conn, "llm_model": "llama3"},
    )

    assert created.status_code == 201
    assert created.json()["llm_provider"] == llm_conn


@respx.mock
async def test_a_model_the_connection_does_not_offer_is_refused(
    authed: AsyncClient, llm_conn: str
) -> None:
    respx.get(MODELS).respond(200, json={"data": [{"id": "llama3", "object": "model"}]})

    response = await authed.post(
        "/api/shows",
        json={"title": "Local", "topic": "t", "llm_provider": llm_conn, "llm_model": "nope"},
    )

    assert response.status_code == 422
    assert "not offered" in response.json()["detail"]


async def test_a_show_cannot_use_a_connection_that_is_missing_or_not_for_models(
    authed: AsyncClient, tts_conn: str
) -> None:
    for provider in (tts_conn, f"conn:{uuid.uuid4()}"):
        response = await authed.post(
            "/api/shows",
            json={"title": "x", "topic": "t", "llm_provider": provider, "llm_model": "m"},
        )
        assert response.status_code == 422, response.text


async def test_a_disabled_connection_is_refused(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    off = await make_connection(db_session, admin_user, "Off", enabled=False)

    response = await authed.post(
        "/api/shows",
        json={"title": "x", "topic": "t", "llm_provider": f"conn:{off.id}", "llm_model": "m"},
    )

    assert response.status_code == 422 and "disabled" in response.text


# --- speakers -----------------------------------------------------------------------------------


async def test_speakers_can_voice_with_a_connection_and_fall_back_to_another(
    authed: AsyncClient, tts_conn: str
) -> None:
    show = (await authed.post("/api/shows", json={"title": "x", "topic": "t"})).json()
    body = [
        {
            "name": "Alex",
            "tts_provider": tts_conn,
            "voice_id": "af_bella",
            "voice_params": {"speed": 1.1, "lang_code": "a"},
            "fallback_tts_provider": "kokoro",
            "fallback_voice_id": "af_bella",
        }
    ]

    saved = await authed.put(f"/api/shows/{show['id']}/speakers", json=body)

    assert saved.status_code == 200
    assert saved.json()[0]["tts_provider"] == tts_conn


async def test_speakers_cannot_use_connections_that_are_missing_or_not_for_voices(
    authed: AsyncClient, llm_conn: str
) -> None:
    show = (await authed.post("/api/shows", json={"title": "x", "topic": "t"})).json()
    ghost = f"conn:{uuid.uuid4()}"

    for body, field in (
        ({"tts_provider": llm_conn}, "tts_provider"),
        ({"tts_provider": ghost}, "tts_provider"),
        ({"fallback_tts_provider": llm_conn, "fallback_voice_id": "v"}, "fallback_tts_provider"),
    ):
        speaker = {"name": "Alex", "tts_provider": "openai", "voice_id": "alloy", **body}
        response = await authed.put(f"/api/shows/{show['id']}/speakers", json=[speaker])
        assert response.status_code == 422, response.text
        assert ["body", 0, field] in [e["loc"] for e in response.json()["detail"]]


async def test_voice_parameters_of_a_connection_are_validated(
    authed: AsyncClient, tts_conn: str
) -> None:
    show = (await authed.post("/api/shows", json={"title": "x", "topic": "t"})).json()
    speaker = {
        "name": "A",
        "tts_provider": tts_conn,
        "voice_id": "v",
        "voice_params": {"speed": 99},
    }

    response = await authed.put(f"/api/shows/{show['id']}/speakers", json=[speaker])

    assert response.status_code == 422


# --- dashboard ----------------------------------------------------------------------------------


async def test_connections_complete_the_onboarding_steps(
    app: FastAPI, authed: AsyncClient, llm_conn: str, tts_conn: str
) -> None:
    app.dependency_overrides[get_settings] = lambda: make_settings()

    onboarding = (await authed.get("/api/dashboard")).json()["onboarding"]

    assert onboarding["provider_configured"] is True and onboarding["voice_configured"] is True


# --- secrets never leak -------------------------------------------------------------------------


@respx.mock
async def test_header_values_and_keys_never_reach_the_logs_or_responses(
    authed: AsyncClient, llm_conn: str, tts_conn: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    respx.get(MODELS).mock(side_effect=httpx.ConnectError("boom"))
    respx.get(VOICES).respond(500, text=f"{HEADER[1]} {KEY}")
    responses = [
        await authed.get("/api/models", params={"provider": llm_conn}),
        await authed.get("/api/voices", params={"provider": tts_conn}),
        await authed.get("/api/connections"),
        await authed.get("/api/providers", params={"capability": "tts"}),
    ]
    for connection in (await authed.get("/api/connections")).json():
        responses.append(await authed.post(f"/api/connections/{connection['id']}/test"))

    for text in [*(r.text for r in responses), caplog.text]:
        assert HEADER[1] not in text and KEY not in text
