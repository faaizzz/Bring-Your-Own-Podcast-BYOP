import httpx
import respx
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr

from byop.config import get_settings
from tests.helpers import make_settings

ELEVEN_VOICES = "https://api.elevenlabs.io/v1/voices"
PAYLOAD = {
    "voices": [
        {
            "voice_id": "abc",
            "name": "Rachel",
            "labels": {"gender": "female", "language": "en"},
            "preview_url": "https://cdn.example/r.mp3",
        }
    ]
}


def configure(app: FastAPI, **overrides: object) -> None:
    app.dependency_overrides[get_settings] = lambda: make_settings(**overrides)


@respx.mock
async def test_lists_elevenlabs_voices(app: FastAPI, authed: AsyncClient) -> None:
    configure(app, elevenlabs_api_key=SecretStr("xi-env-key-0123456789"))
    route = respx.get(ELEVEN_VOICES).respond(200, json=PAYLOAD)

    response = await authed.get("/api/voices", params={"provider": "elevenlabs"})

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "abc",
            "name": "Rachel",
            "language": "en",
            "gender": "female",
            "preview_url": "https://cdn.example/r.mp3",
        }
    ]
    assert route.calls.last.request.headers["xi-api-key"] == "xi-env-key-0123456789"


async def test_openai_voices_need_no_network(app: FastAPI, authed: AsyncClient) -> None:
    configure(app, openai_api_key=SecretStr("sk-env-key-0123456789"))

    response = await authed.get("/api/voices", params={"provider": "openai"})

    assert response.status_code == 200
    assert "alloy" in {v["id"] for v in response.json()}


@respx.mock
async def test_results_are_cached_per_credential(app: FastAPI, authed: AsyncClient) -> None:
    route = respx.get(ELEVEN_VOICES).respond(200, json=PAYLOAD)

    configure(app, elevenlabs_api_key=SecretStr("xi-key-one-0123456789"))
    await authed.get("/api/voices", params={"provider": "elevenlabs"})
    await authed.get("/api/voices", params={"provider": "elevenlabs"})
    assert route.call_count == 1

    configure(app, elevenlabs_api_key=SecretStr("xi-key-two-0123456789"))
    await authed.get("/api/voices", params={"provider": "elevenlabs"})
    assert route.call_count == 2


async def test_unconfigured_provider_is_a_conflict(authed: AsyncClient) -> None:
    response = await authed.get("/api/voices", params={"provider": "elevenlabs"})

    assert response.status_code == 409


async def test_only_tts_providers_are_accepted(authed: AsyncClient) -> None:
    assert (await authed.get("/api/voices", params={"provider": "langfuse"})).status_code == 422


@respx.mock
async def test_upstream_failures_are_a_bad_gateway(app: FastAPI, authed: AsyncClient) -> None:
    configure(app, elevenlabs_api_key=SecretStr("xi-env-key-0123456789"))
    respx.get(ELEVEN_VOICES).mock(side_effect=httpx.ConnectError("down"))

    response = await authed.get("/api/voices", params={"provider": "elevenlabs"})

    assert response.status_code == 502
    assert "xi-env" not in response.text


async def test_requires_a_session(client: AsyncClient) -> None:
    assert (await client.get("/api/voices")).status_code == 401


KOKORO = "http://kokoro:8880/v1"


@respx.mock
async def test_lists_kokoro_voices(app: FastAPI, authed: AsyncClient) -> None:
    configure(app, kokoro_base_url=KOKORO)
    respx.get(f"{KOKORO}/audio/voices").respond(200, json={"voices": ["af_bella", "bm_george"]})

    response = await authed.get("/api/voices", params={"provider": "kokoro"})

    assert response.status_code == 200
    assert [(v["id"], v["name"], v["language"], v["gender"]) for v in response.json()] == [
        ("af_bella", "Bella", "en-US", "female"),
        ("bm_george", "George", "en-GB", "male"),
    ]


@respx.mock
async def test_kokoro_can_be_configured_through_the_integrations_api(
    authed: AsyncClient,
) -> None:
    await authed.put("/api/integrations/kokoro", json={"base_url": KOKORO})
    respx.get(f"{KOKORO}/audio/voices").respond(200, json={"voices": ["af_bella"]})

    response = await authed.get("/api/voices", params={"provider": "kokoro"})

    assert response.status_code == 200 and response.json()[0]["id"] == "af_bella"


@respx.mock
async def test_voices_without_a_provider_use_the_default(app: FastAPI, authed: AsyncClient) -> None:
    configure(app, kokoro_base_url=KOKORO)
    respx.get(f"{KOKORO}/audio/voices").respond(200, json={"voices": ["af_bella"]})

    response = await authed.get("/api/voices")

    assert response.status_code == 200
    assert response.json()[0]["id"] == "af_bella"


async def test_voices_without_a_provider_and_nothing_configured(authed: AsyncClient) -> None:
    response = await authed.get("/api/voices")

    assert response.status_code == 409
    assert "No text-to-speech provider" in response.json()["detail"]


@respx.mock
async def test_default_provider_is_kokoro_without_paid_keys(
    app: FastAPI, authed: AsyncClient
) -> None:
    configure(app, kokoro_base_url=KOKORO)
    respx.get(f"{KOKORO}/audio/voices").respond(200, json={"voices": []})

    assert (await authed.get("/api/voices/default-provider")).json() == {"provider": "kokoro"}


async def test_default_provider_prefers_a_paid_key(app: FastAPI, authed: AsyncClient) -> None:
    configure(app, openai_api_key=SecretStr("sk-env-key-0123456789"), kokoro_base_url=KOKORO)

    assert (await authed.get("/api/voices/default-provider")).json() == {"provider": "openai"}


async def test_default_provider_is_null_when_nothing_is_usable(authed: AsyncClient) -> None:
    assert (await authed.get("/api/voices/default-provider")).json() == {"provider": None}


async def test_default_provider_requires_a_session(client: AsyncClient) -> None:
    assert (await client.get("/api/voices/default-provider")).status_code == 401


@respx.mock
async def test_an_empty_voice_list_is_not_cached(app: FastAPI, authed: AsyncClient) -> None:
    configure(app, kokoro_base_url=KOKORO)
    route = respx.get(f"{KOKORO}/audio/voices")
    route.respond(200, json={"voices": []})
    assert (await authed.get("/api/voices", params={"provider": "kokoro"})).json() == []

    route.respond(200, json={"voices": [{"id": "af_bella"}]})
    response = await authed.get("/api/voices", params={"provider": "kokoro"})

    assert [v["id"] for v in response.json()] == ["af_bella"]


# --- speech models ----------------------------------------------------------------------------

OPENROUTER_SPEECH = "https://openrouter.ai/api/v1/models?output_modalities=speech"
SPEECH = {
    "data": [
        {
            "id": "mistralai/voxtral-mini-tts-3-0",
            "name": "Voxtral",
            "supported_voices": ["en_paul_neutral", "fr_marie_happy"],
        },
        {"id": "hexgrad/kokoro-82m", "name": "Kokoro", "supported_voices": ["af_bella"]},
    ]
}


@respx.mock
async def test_lists_openrouter_speech_models(app: FastAPI, authed: AsyncClient) -> None:
    configure(app, openrouter_api_key=SecretStr("sk-or-speech-01-0123456789"))
    respx.get(OPENROUTER_SPEECH).respond(200, json=SPEECH)

    response = await authed.get("/api/voices/models", params={"provider": "openrouter"})

    assert response.status_code == 200
    assert response.json() == {
        "param": "model",
        "required": True,
        "default": None,
        "voices_follow_model": True,
        "models": [
            {"id": "mistralai/voxtral-mini-tts-3-0", "name": "Voxtral", "description": None},
            {"id": "hexgrad/kokoro-82m", "name": "Kokoro", "description": None},
        ],
    }


@respx.mock
async def test_openrouter_voices_depend_on_the_model_and_are_cached_per_model(
    app: FastAPI, authed: AsyncClient
) -> None:
    configure(app, openrouter_api_key=SecretStr("sk-or-speech-02-0123456789"))
    route = respx.get(OPENROUTER_SPEECH).respond(200, json=SPEECH)
    params = {"provider": "openrouter", "model": "mistralai/voxtral-mini-tts-3-0"}

    first = await authed.get("/api/voices", params=params)
    again = await authed.get("/api/voices", params=params)
    other = await authed.get(
        "/api/voices", params={"provider": "openrouter", "model": "hexgrad/kokoro-82m"}
    )

    assert [v["id"] for v in first.json()] == ["en_paul_neutral", "fr_marie_happy"]
    assert again.json() == first.json()
    assert [v["id"] for v in other.json()] == ["af_bella"]
    assert route.call_count == 2  # one per model; the repeat came from the cache


async def test_the_model_does_not_change_the_voices_of_other_providers(
    app: FastAPI, authed: AsyncClient
) -> None:
    configure(app, openai_api_key=SecretStr("sk-speech-openai-0123456789"))

    plain = await authed.get("/api/voices", params={"provider": "openai"})
    with_model = await authed.get("/api/voices", params={"provider": "openai", "model": "tts-1"})

    assert plain.json() == with_model.json()


async def test_openai_speech_models_and_default(app: FastAPI, authed: AsyncClient) -> None:
    configure(app, openai_api_key=SecretStr("sk-speech-openai-0123456789"))

    body = (await authed.get("/api/voices/models", params={"provider": "openai"})).json()

    assert (body["param"], body["required"], body["default"]) == ("model", False, "gpt-4o-mini-tts")
    assert [m["id"] for m in body["models"]] == ["gpt-4o-mini-tts", "tts-1", "tts-1-hd"]


@respx.mock
async def test_elevenlabs_speech_models_use_model_id(app: FastAPI, authed: AsyncClient) -> None:
    configure(app, elevenlabs_api_key=SecretStr("xi-speech-01-0123456789"))
    respx.get("https://api.elevenlabs.io/v1/models").respond(
        200, json=[{"model_id": "eleven_multilingual_v2", "name": "Multilingual v2"}]
    )

    body = (await authed.get("/api/voices/models", params={"provider": "elevenlabs"})).json()

    assert (body["param"], body["required"], body["default"]) == (
        "model_id",
        False,
        "eleven_multilingual_v2",
    )
    assert body["models"][0]["name"] == "Multilingual v2"


async def test_kokoro_has_no_choice_of_model(app: FastAPI, authed: AsyncClient) -> None:
    configure(app, kokoro_base_url=KOKORO)

    body = (await authed.get("/api/voices/models", params={"provider": "kokoro"})).json()

    assert body == {
        "param": None,
        "required": False,
        "default": None,
        "voices_follow_model": False,
        "models": [],
    }


@respx.mock
async def test_a_connection_without_a_models_route_gives_an_empty_list_to_type_into(
    authed: AsyncClient,
) -> None:
    saved = await authed.post(
        "/api/connections", json={"name": "Gateway", "base_url": "http://gw.local/v1", "tts": True}
    )
    respx.get("http://gw.local/v1/models").respond(404)

    response = await authed.get(
        "/api/voices/models", params={"provider": f"conn:{saved.json()['id']}"}
    )

    assert response.status_code == 200
    assert response.json()["models"] == [] and response.json()["param"] == "model"


@respx.mock
async def test_speech_models_are_cached(app: FastAPI, authed: AsyncClient) -> None:
    configure(app, openrouter_api_key=SecretStr("sk-or-speech-03-0123456789"))
    route = respx.get(OPENROUTER_SPEECH).respond(200, json=SPEECH)

    await authed.get("/api/voices/models", params={"provider": "openrouter"})
    await authed.get("/api/voices/models", params={"provider": "openrouter"})

    assert route.call_count == 1


@respx.mock
async def test_speech_model_errors(app: FastAPI, authed: AsyncClient) -> None:
    unconfigured = await authed.get("/api/voices/models", params={"provider": "openrouter"})
    configure(app, openrouter_api_key=SecretStr("sk-or-speech-04-0123456789"))
    respx.get(OPENROUTER_SPEECH).mock(side_effect=httpx.ConnectError("down"))

    down = await authed.get("/api/voices/models", params={"provider": "openrouter"})

    assert unconfigured.status_code == 409
    assert down.status_code == 502 and "sk-or" not in down.text
    assert (await authed.get("/api/voices/models")).status_code == 422  # provider is required
    assert (await authed.get("/api/voices/models", params={"provider": "x"})).status_code == 422


async def test_speech_models_require_a_session(client: AsyncClient) -> None:
    assert (
        await client.get("/api/voices/models", params={"provider": "openai"})
    ).status_code == 401
