import logging

import httpx
import pytest
import respx
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import get_settings
from byop.models import ProviderCredential
from tests.helpers import make_settings

KEY = "sk-live-abcdef1234567890"


def use_settings(app: FastAPI, **overrides: object) -> None:
    app.dependency_overrides[get_settings] = lambda: make_settings(**overrides)


async def put(client: AsyncClient, provider: str = "openai", **body: object) -> httpx.Response:
    return await client.put(f"/api/integrations/{provider}", json={"api_key": KEY, **body})


async def test_unauthenticated_requests_are_rejected(client: AsyncClient) -> None:
    assert (await client.get("/api/integrations/openai")).status_code == 401
    assert (await client.put("/api/integrations/openai", json={"api_key": KEY})).status_code == 401
    assert (await client.delete("/api/integrations/openai")).status_code == 401
    assert (await client.post("/api/integrations/openai/test")).status_code == 401


async def test_get_reports_none_when_nothing_is_configured(authed: AsyncClient) -> None:
    response = await authed.get("/api/integrations/openai")

    assert response.status_code == 200
    assert response.json() == {
        "provider": "openai",
        "source": "none",
        "enabled": True,
        "api_key_masked": None,
        "base_url": None,
        "extra_masked": {},
        "problem": None,
    }


async def test_get_reports_the_environment_source_masked(app: FastAPI, authed: AsyncClient) -> None:
    use_settings(app, openai_api_key=SecretStr("sk-from-env-9876543210"))

    body = (await authed.get("/api/integrations/openai")).json()

    assert body["source"] == "env"
    assert body["api_key_masked"] == "sk-…3210"
    assert "from-env" not in str(body)


async def test_put_then_get_never_returns_the_secret(authed: AsyncClient) -> None:
    saved = await put(authed, base_url="https://proxy.example/v1/")
    fetched = await authed.get("/api/integrations/openai")

    for response in (saved, fetched):
        assert response.status_code == 200
        assert KEY not in response.text
        body = response.json()
        assert body["source"] == "user"
        assert body["api_key_masked"] == "sk-…7890"
        assert body["base_url"] == "https://proxy.example/v1"


async def test_the_stored_value_is_ciphertext(
    authed: AsyncClient, db_session: AsyncSession
) -> None:
    await put(authed)

    stored = (await db_session.scalars(select(ProviderCredential))).one()

    assert KEY not in stored.secret_encrypted


async def test_user_override_beats_the_environment(app: FastAPI, authed: AsyncClient) -> None:
    use_settings(app, openai_api_key=SecretStr("sk-from-env-9876543210"))

    await put(authed)

    assert (await authed.get("/api/integrations/openai")).json()["source"] == "user"


async def test_update_without_a_key_keeps_the_stored_one(authed: AsyncClient) -> None:
    await put(authed)

    await authed.put("/api/integrations/openai", json={"enabled": False})

    response = await authed.put("/api/integrations/openai", json={"enabled": True})

    assert response.status_code == 200
    assert response.json()["source"] == "user"
    assert response.json()["api_key_masked"] == "sk-…7890"


async def test_disabling_an_override_falls_back_to_the_environment(
    app: FastAPI, authed: AsyncClient
) -> None:
    use_settings(app, openai_api_key=SecretStr("sk-from-env-9876543210"))
    await put(authed, enabled=False)

    body = (await authed.get("/api/integrations/openai")).json()

    assert body["source"] == "env"
    assert body["enabled"] is False


async def test_delete_removes_the_override_and_is_idempotent(
    app: FastAPI, authed: AsyncClient
) -> None:
    use_settings(app, openai_api_key=SecretStr("sk-from-env-9876543210"))
    await put(authed)

    assert (await authed.delete("/api/integrations/openai")).status_code == 204
    assert (await authed.delete("/api/integrations/openai")).status_code == 204
    assert (await authed.get("/api/integrations/openai")).json()["source"] == "env"


@pytest.mark.parametrize(
    ("provider", "body", "needle"),
    [
        ("openai", {}, "API key"),
        ("openrouter", {"base_url": "https://x.example"}, "API key"),
        ("elevenlabs", {"enabled": True}, "API key"),
        ("langfuse", {"extra": {"public_key": "pk"}}, "API key"),
        ("kokoro", {"api_key": "irrelevant"}, "base URL"),
    ],
)
async def test_a_new_override_must_be_usable(
    authed: AsyncClient, provider: str, body: dict[str, object], needle: str
) -> None:
    response = await authed.put(f"/api/integrations/{provider}", json=body)

    assert response.status_code == 422
    assert needle in response.text


async def test_kokoro_only_needs_a_base_url(authed: AsyncClient) -> None:
    response = await authed.put(
        "/api/integrations/kokoro", json={"base_url": "http://kokoro:8880/v1"}
    )

    assert response.status_code == 200
    assert response.json()["api_key_masked"] is None


async def test_unknown_providers_and_bad_urls_are_rejected(authed: AsyncClient) -> None:
    assert (await authed.get("/api/integrations/acme")).status_code == 422
    assert (await put(authed, base_url="not a url")).status_code == 422
    assert (await put(authed, base_url="ftp://host/x")).status_code == 422


# --- live test endpoint ---------------------------------------------------------------


@respx.mock
async def test_openai_check_calls_models_with_the_bearer_key(authed: AsyncClient) -> None:
    route = respx.get("https://api.openai.com/v1/models").respond(200, json={"data": []})
    await put(authed)

    result = await authed.post("/api/integrations/openai/test")

    assert result.json() == {"ok": True, "detail": "Connection works"}
    assert route.calls.last.request.headers["authorization"] == f"Bearer {KEY}"


@respx.mock
async def test_check_honours_a_custom_openai_base_url(authed: AsyncClient) -> None:
    route = respx.get("https://proxy.example/v1/models").respond(200, json={})
    await put(authed, base_url="https://proxy.example/v1")

    assert (await authed.post("/api/integrations/openai/test")).json()["ok"] is True
    assert route.called


@respx.mock
async def test_openrouter_check(authed: AsyncClient) -> None:
    route = respx.get("https://openrouter.ai/api/v1/auth/key").respond(200, json={"data": {}})
    await put(authed, "openrouter")

    assert (await authed.post("/api/integrations/openrouter/test")).json()["ok"] is True
    assert route.calls.last.request.headers["authorization"] == f"Bearer {KEY}"


@respx.mock
async def test_elevenlabs_check_uses_the_xi_api_key_header(authed: AsyncClient) -> None:
    route = respx.get("https://api.elevenlabs.io/v1/models").respond(200, json=[])
    await put(authed, "elevenlabs")

    assert (await authed.post("/api/integrations/elevenlabs/test")).json()["ok"] is True
    assert route.calls.last.request.headers["xi-api-key"] == KEY


@respx.mock
async def test_langfuse_check_uses_basic_auth_with_both_keys(authed: AsyncClient) -> None:
    route = respx.get("https://lf.example/api/public/projects").respond(200, json={"data": []})
    await put(authed, "langfuse", base_url="https://lf.example", extra={"public_key": "pk-lf-1"})

    assert (await authed.post("/api/integrations/langfuse/test")).json()["ok"] is True
    request = route.calls.last.request
    assert httpx.BasicAuth("pk-lf-1", KEY)._auth_header == request.headers["authorization"]


@respx.mock
async def test_kokoro_check(authed: AsyncClient) -> None:
    voices = respx.get("http://kokoro:8880/v1/audio/voices").respond(200, json={})
    await authed.put("/api/integrations/kokoro", json={"base_url": "http://kokoro:8880/v1"})

    assert (await authed.post("/api/integrations/kokoro/test")).json()["ok"] is True
    assert voices.called


async def test_openai_compatible_servers_are_connections_not_integrations(
    authed: AsyncClient,
) -> None:
    for call in (
        authed.get("/api/integrations/openai_compatible"),
        authed.put("/api/integrations/openai_compatible", json={"base_url": "http://x.example"}),
        authed.delete("/api/integrations/openai_compatible"),
        authed.post("/api/integrations/openai_compatible/test"),
    ):
        assert (await call).status_code == 404


@respx.mock
@pytest.mark.parametrize(
    ("status", "detail"),
    [
        (401, "Authentication failed (HTTP 401)"),
        (403, "Authentication failed (HTTP 403)"),
        (500, "Unexpected response (HTTP 500)"),
    ],
)
async def test_failed_checks_explain_why_without_leaking(
    authed: AsyncClient, status: int, detail: str
) -> None:
    respx.get("https://api.openai.com/v1/models").respond(status, text=f"nope {KEY}")
    await put(authed)

    response = await authed.post("/api/integrations/openai/test")

    assert response.json() == {"ok": False, "detail": detail}
    assert KEY not in response.text


@respx.mock
async def test_network_failures_are_reported(authed: AsyncClient) -> None:
    await put(authed)
    respx.get("https://api.openai.com/v1/models").mock(side_effect=httpx.ConnectError("boom"))
    refused = await authed.post("/api/integrations/openai/test")
    respx.get("https://api.openai.com/v1/models").mock(side_effect=httpx.ReadTimeout("slow"))
    slow = await authed.post("/api/integrations/openai/test")

    assert refused.json() == {"ok": False, "detail": "Could not connect (ConnectError)"}
    assert slow.json() == {"ok": False, "detail": "The provider did not answer in time"}


async def test_checking_an_unconfigured_provider(authed: AsyncClient) -> None:
    response = await authed.post("/api/integrations/openai/test")

    assert response.json() == {"ok": False, "detail": "Not configured"}


@respx.mock
async def test_check_uses_the_environment_key_when_there_is_no_override(
    app: FastAPI, authed: AsyncClient
) -> None:
    use_settings(app, openai_api_key=SecretStr("sk-from-env-9876543210"))
    route = respx.get("https://api.openai.com/v1/models").respond(200, json={})

    assert (await authed.post("/api/integrations/openai/test")).json()["ok"] is True
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-from-env-9876543210"


# --- secrets never reach the logs ------------------------------------------------------


@respx.mock
async def test_secrets_never_appear_in_logs_or_responses(
    authed: AsyncClient,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    from byop.logging import configure_logging

    configure_logging("DEBUG")
    caplog.set_level(logging.DEBUG)
    respx.get("https://api.openai.com/v1/models").respond(401, text="bad key")

    responses = [
        await put(authed),
        await authed.get("/api/integrations/openai"),
        await authed.post("/api/integrations/openai/test"),
        await authed.delete("/api/integrations/openai"),
    ]

    captured = capsys.readouterr()
    everything = captured.out + captured.err + caplog.text + "".join(r.text for r in responses)
    assert KEY not in everything
    assert "abcdef1234567890" not in everything
