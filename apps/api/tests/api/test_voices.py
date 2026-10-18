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

    response = await authed.get("/api/voices")  # openai is the default

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
    assert (await authed.get("/api/voices", params={"provider": "kokoro"})).status_code == 422


@respx.mock
async def test_upstream_failures_are_a_bad_gateway(app: FastAPI, authed: AsyncClient) -> None:
    configure(app, elevenlabs_api_key=SecretStr("xi-env-key-0123456789"))
    respx.get(ELEVEN_VOICES).mock(side_effect=httpx.ConnectError("down"))

    response = await authed.get("/api/voices", params={"provider": "elevenlabs"})

    assert response.status_code == 502
    assert "xi-env" not in response.text


async def test_requires_a_session(client: AsyncClient) -> None:
    assert (await client.get("/api/voices")).status_code == 401
