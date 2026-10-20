import json
import uuid
from dataclasses import replace

import pytest
import respx
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings, get_settings
from byop.models import User
from byop.redis_client import get_redis_client
from byop.schemas.discovery import DiscoveryStatus
from byop.services.discovery import DiscoveryRequest, choose_model
from byop.services.discovery_jobs import create_job, load_job
from byop.services.provider_ref import ProviderRef
from byop.services.user_settings import load_discovery_choice
from byop.tasks import discovery as tasks
from tests.helpers import make_settings
from tests.models.factories import make_connection, make_show, make_user
from tests.providers.llm.helpers import OPENROUTER_URL, completion

pytestmark = pytest.mark.usefixtures("fake_dns")

URL = "/api/settings/discovery-model"
MODELS = "https://openrouter.ai/api/v1/models"
CATALOG = {
    "data": [
        {"id": "vendor/model", "name": "M", "architecture": {"output_modalities": ["text"]}},
        {"id": "vendor/speech", "name": "S", "architecture": {"output_modalities": ["audio"]}},
    ]
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


# --- the endpoint ---------------------------------------------------------------------------


@respx.mock
async def test_nothing_is_saved_by_default_and_the_effective_model_is_the_fallback(
    authed: AsyncClient,
) -> None:
    respx.get(MODELS).respond(200, json=CATALOG)

    body = (await authed.get(URL)).json()

    assert (body["provider"], body["model"]) == (None, None)
    assert (body["effective"]["model"], body["effective"]["source"]) == ("vendor/model", "default")


async def test_without_any_model_the_effective_choice_is_empty(
    app: FastAPI, authed: AsyncClient
) -> None:
    app.dependency_overrides[get_settings] = lambda: make_settings()

    body = (await authed.get(URL)).json()

    assert body["effective"] is None


@respx.mock
async def test_a_saved_model_wins_over_env_and_default_and_shows_source_settings(
    app: FastAPI, authed: AsyncClient
) -> None:
    app.dependency_overrides[get_settings] = lambda: configured(
        discovery_llm_provider="openrouter", discovery_llm_model="vendor/from-env"
    )
    respx.get(MODELS).respond(200, json=CATALOG)

    saved = await authed.put(URL, json={"provider": "openrouter", "model": "perplexity/sonar"})
    fetched = (await authed.get(URL)).json()

    assert saved.status_code == 200
    assert saved.json() == fetched | {"warnings": []}
    assert (fetched["provider"], fetched["model"]) == ("openrouter", "perplexity/sonar")
    assert fetched["effective"] == {
        "provider": "openrouter",
        "provider_label": "OpenRouter",
        "model": "perplexity/sonar",
        "source": "user_setting",
        "web_search": "yes",
        "message": None,
    }


@respx.mock
async def test_the_discover_dialogs_model_endpoint_shows_the_saved_choice(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    respx.get(MODELS).respond(200, json=CATALOG)
    show = await make_show(db_session, admin_user)
    show.llm_provider, show.llm_model = "openrouter", "vendor/model"
    await db_session.flush()

    await authed.put(URL, json={"provider": "openrouter", "model": "perplexity/sonar"})
    shown = (
        await authed.get("/api/sources/discover/model", params={"show_id": str(show.id)})
    ).json()

    assert (shown["model"], shown["source"]) == ("perplexity/sonar", "user_setting")


@respx.mock
async def test_clearing_falls_back_to_env_then_show_then_default(
    app: FastAPI, authed: AsyncClient
) -> None:
    respx.get(MODELS).respond(200, json=CATALOG)
    await authed.put(URL, json={"provider": "openrouter", "model": "perplexity/sonar"})

    cleared = await authed.delete(URL)

    assert cleared.status_code == 200
    body = cleared.json()
    assert (body["provider"], body["model"]) == (None, None)
    assert body["effective"]["source"] == "default"
    # Clearing twice is fine.
    assert (await authed.delete(URL)).status_code == 200


@respx.mock
async def test_a_model_that_cannot_search_is_a_422_with_the_clear_message(
    app: FastAPI, authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    app.dependency_overrides[get_settings] = lambda: configured(
        openai_api_key=SecretStr("sk-openai-test-123456")
    )
    respx.get(MODELS).respond(200, json=CATALOG)
    conn = await make_connection(db_session, admin_user, "Plain box")

    plain = await authed.put(URL, json={"provider": f"conn:{conn.id}", "model": "llama3"})
    gone = await authed.put(URL, json={"provider": "openrouter", "model": "vendor/unknown"})
    speech = await authed.put(URL, json={"provider": "openrouter", "model": "vendor/speech"})
    openai = await authed.put(URL, json={"provider": "openai", "model": "gpt-4o"})

    for response in (plain, gone, speech, openai):
        assert response.status_code == 422
        assert "cannot search the web" in response.json()["detail"]
    assert "Plain box" in plain.json()["detail"] and "'llama3'" in plain.json()["detail"]
    assert "Settings › Integrations › Discovery model" in plain.json()["detail"]
    assert "gpt-4o-search-preview" in openai.json()["detail"]
    assert (await authed.get(URL)).json()["provider"] is None  # nothing was saved


@respx.mock
async def test_a_model_whose_capability_is_unknown_is_saved_with_a_warning(
    authed: AsyncClient,
) -> None:
    respx.get(MODELS).respond(503)

    response = await authed.put(URL, json={"provider": "openrouter", "model": "vendor/model"})

    assert response.status_code == 200
    [warning] = response.json()["warnings"]
    assert "Could not check whether 'vendor/model' can search the web" in warning
    assert response.json()["model"] == "vendor/model"


async def test_a_connection_marked_for_web_search_can_be_saved(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    conn = await make_connection(db_session, admin_user, "Sonar box", web_search=True)

    response = await authed.put(URL, json={"provider": f"conn:{conn.id}", "model": "sonar"})

    assert response.status_code == 200
    assert response.json()["effective"]["provider_label"] == "Sonar box"
    assert response.json()["effective"]["source"] == "user_setting"


async def test_the_provider_is_validated_like_a_shows(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    other = await make_user(db_session, "other@example.com")
    theirs = await make_connection(db_session, other, "Theirs", web_search=True)
    off = await make_connection(db_session, admin_user, "Off", web_search=True, enabled=False)
    voices = await make_connection(db_session, admin_user, "Voices", llm=False, tts=True)
    missing = "conn:00000000-0000-4000-8000-000000000000"

    for provider in (f"conn:{theirs.id}", f"conn:{off.id}", f"conn:{voices.id}", missing):
        response = await authed.put(URL, json={"provider": provider, "model": "m"})
        assert response.status_code == 422, provider
        assert response.json()["detail"][0]["loc"] == ["body", "provider"]
    for body in (
        {"provider": "kokoro", "model": "m"},  # not a language-model provider
        {"provider": "nope", "model": "m"},
        {"provider": "openrouter", "model": "  "},
        {"provider": "openrouter"},
    ):
        assert (await authed.put(URL, json=body)).status_code == 422


@respx.mock
async def test_each_user_has_their_own_choice(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    respx.get(MODELS).respond(200, json=CATALOG)
    await authed.put(URL, json={"provider": "openrouter", "model": "perplexity/sonar"})
    other = await make_user(db_session, "other@example.com")

    mine = await load_discovery_choice(db_session, admin_user.id)
    theirs = await load_discovery_choice(db_session, other.id)

    assert mine.model == "perplexity/sonar" and theirs.model is None


async def test_requires_a_session(client: AsyncClient) -> None:
    assert (await client.get(URL)).status_code == 401
    assert (await client.put(URL, json={})).status_code == 401
    assert (await client.delete(URL)).status_code == 401


# --- a connection used by the setting ------------------------------------------------------


async def test_a_connection_chosen_as_the_discovery_model_cannot_be_deleted_or_switched_off(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    conn = await make_connection(db_session, admin_user, "Sonar box", web_search=True)
    await authed.put(URL, json={"provider": f"conn:{conn.id}", "model": "sonar"})

    delete = await authed.delete(f"/api/connections/{conn.id}")
    disable = await authed.patch(f"/api/connections/{conn.id}", json={"enabled": False})
    no_llm = await authed.patch(f"/api/connections/{conn.id}", json={"llm": False, "tts": True})

    for response in (delete, disable, no_llm):
        assert response.status_code == 409
        assert "discovery model setting" in response.json()["detail"]

    await authed.delete(URL)
    assert (await authed.delete(f"/api/connections/{conn.id}")).status_code == 204


# --- the pure choice and the places that use it ----------------------------------------------


def test_the_precedence_is_settings_then_env_then_show_then_default() -> None:
    settings = configured(
        discovery_llm_provider="openrouter", discovery_llm_model="vendor/from-env"
    )
    base = DiscoveryRequest(uuid.uuid4(), None, "t", llm_provider="openai", llm_model="gpt-show")
    saved = replace(base, discovery_llm_provider="openai", discovery_llm_model="gpt-saved")

    assert choose_model(settings, saved) == (
        ProviderRef.parse("openai"),
        "gpt-saved",
        "user_setting",
    )
    assert choose_model(settings, base)[1:] == ("vendor/from-env", "discovery_setting")
    assert choose_model(configured(), base)[1:] == ("gpt-show", "show")
    assert choose_model(configured(), replace(base, llm_provider=None))[1:] == (
        "vendor/model",
        "default",
    )
    # Half a choice is no choice.
    half = replace(base, discovery_llm_provider="openai", discovery_llm_model=None)
    assert choose_model(configured(), half)[1:] == ("gpt-show", "show")


@respx.mock
async def test_the_worker_uses_the_saved_choice(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    respx.get(MODELS).respond(200, json=CATALOG)
    route = respx.post(OPENROUTER_URL).respond(200, json=completion(json.dumps({"candidates": []})))
    await authed.put(URL, json={"provider": "openrouter", "model": "perplexity/sonar"})
    job_id = await create_job(get_redis_client(), admin_user.id, None)

    await tasks.run_discovery_job(
        job_id,
        DiscoveryRequest(admin_user.id, None, "rust"),  # built without the choice
        session=db_session,
        redis=get_redis_client(),
        settings=configured(),
    )

    record = await load_job(get_redis_client(), job_id)
    assert record is not None and record.status is DiscoveryStatus.DONE
    assert json.loads(route.calls.last.request.content)["model"] == "perplexity/sonar"


@respx.mock
async def test_the_start_endpoints_hand_the_saved_choice_to_the_check(
    authed: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[object, ...]] = []
    monkeypatch.setattr(tasks.discover_sources_task, "delay", lambda *args: sent.append(args))
    respx.get(MODELS).respond(200, json=CATALOG)
    await authed.put(URL, json={"provider": "openrouter", "model": "perplexity/sonar"})
    show = await authed.post("/api/shows", json={"title": "Rust", "topic": "rust"})
    # The show's own model cannot search, but the saved choice can, so nothing is refused.
    await authed.patch(
        f"/api/shows/{show.json()['id']}", json={"llm_provider": "openai", "llm_model": "gpt-4o"}
    )

    started = await authed.post(f"/api/shows/{show.json()['id']}/sources/discover")
    draft = await authed.post(
        "/api/sources/discover",
        json={"topic": "rust", "llm_provider": "openai", "llm_model": "gpt-4o"},
    )

    assert started.status_code == 202 and draft.status_code == 202
    assert len(sent) == 2
