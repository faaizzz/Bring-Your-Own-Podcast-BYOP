import httpx
import respx
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr

from byop.config import get_settings
from tests.helpers import make_settings

OPENROUTER_MODELS = "https://openrouter.ai/api/v1/models"
PAYLOAD = {
    "data": [
        {
            "id": "a/b",
            "name": "A B",
            "context_length": 8000,
            "pricing": {"prompt": "0.000001", "completion": "0.000002"},
        }
    ]
}


def configure(app: FastAPI, **overrides: object) -> None:
    app.dependency_overrides[get_settings] = lambda: make_settings(**overrides)


@respx.mock
async def test_lists_openrouter_models_with_prices(app: FastAPI, authed: AsyncClient) -> None:
    configure(app, openrouter_api_key=SecretStr("sk-or-env-key-123456"))
    respx.get(OPENROUTER_MODELS).respond(200, json=PAYLOAD)

    response = await authed.get("/api/models", params={"provider": "openrouter"})

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "a/b",
            "name": "A B",
            "context_length": 8000,
            "prompt_price_per_million": "1",
            "completion_price_per_million": "2",
        }
    ]


@respx.mock
async def test_openrouter_is_the_default_provider(app: FastAPI, authed: AsyncClient) -> None:
    configure(app, openrouter_api_key=SecretStr("sk-or-env-key-123456"))
    respx.get(OPENROUTER_MODELS).respond(200, json=PAYLOAD)

    assert (await authed.get("/api/models")).status_code == 200


@respx.mock
async def test_results_are_cached_for_the_same_credentials(
    app: FastAPI, authed: AsyncClient
) -> None:
    configure(app, openrouter_api_key=SecretStr("sk-or-env-key-123456"))
    route = respx.get(OPENROUTER_MODELS).respond(200, json=PAYLOAD)

    first = await authed.get("/api/models")
    second = await authed.get("/api/models")

    assert first.json() == second.json()
    assert route.call_count == 1


@respx.mock
async def test_a_different_key_does_not_share_the_cache(app: FastAPI, authed: AsyncClient) -> None:
    route = respx.get(OPENROUTER_MODELS).respond(200, json=PAYLOAD)

    configure(app, openrouter_api_key=SecretStr("sk-or-key-one-111111"))
    await authed.get("/api/models")
    configure(app, openrouter_api_key=SecretStr("sk-or-key-two-222222"))
    await authed.get("/api/models")

    assert route.call_count == 2


@respx.mock
async def test_the_cache_expires_after_an_hour(app: FastAPI, authed: AsyncClient) -> None:
    from byop.models.enums import CredentialProvider
    from byop.redis_client import get_redis_client
    from byop.services.credentials import ProviderConfig
    from byop.services.models import CACHE_TTL_SECONDS, cache_key

    key = "sk-or-env-key-123456"
    configure(app, openrouter_api_key=SecretStr(key))
    respx.get(OPENROUTER_MODELS).respond(200, json=PAYLOAD)

    await authed.get("/api/models")

    redis = get_redis_client()
    config = ProviderConfig(CredentialProvider.OPENROUTER, "env", SecretStr(key))
    assert 0 < await redis.ttl(cache_key(config)) <= CACHE_TTL_SECONDS == 3600


@respx.mock
async def test_a_connection_uses_its_saved_base_url(authed: AsyncClient) -> None:
    saved = await authed.post(
        "/api/connections",
        json={"name": "Ollama", "base_url": "http://host.docker.internal:11434/v1"},
    )
    assert saved.status_code == 201
    respx.get("http://host.docker.internal:11434/v1/models").respond(
        200,
        json={
            "object": "list",
            "data": [{"id": "llama3.1", "object": "model", "created": 0, "owned_by": "x"}],
        },
    )

    response = await authed.get("/api/models", params={"provider": f"conn:{saved.json()['id']}"})

    assert response.status_code == 200
    assert response.json()[0]["id"] == "llama3.1"


async def test_unconfigured_provider_is_a_conflict(authed: AsyncClient) -> None:
    response = await authed.get("/api/models", params={"provider": "openai"})

    assert response.status_code == 409
    assert "not configured" in response.json()["detail"]


async def test_only_llm_providers_are_accepted(authed: AsyncClient) -> None:
    assert (await authed.get("/api/models", params={"provider": "elevenlabs"})).status_code == 422


@respx.mock
async def test_upstream_failure_is_a_bad_gateway(app: FastAPI, authed: AsyncClient) -> None:
    configure(app, openrouter_api_key=SecretStr("sk-or-env-key-123456"))
    respx.get(OPENROUTER_MODELS).mock(side_effect=httpx.ConnectError("down"))

    response = await authed.get("/api/models")

    assert response.status_code == 502
    assert "sk-or" not in response.text


async def test_requires_a_session(client: AsyncClient) -> None:
    assert (await client.get("/api/models")).status_code == 401
