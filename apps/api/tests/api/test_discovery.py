import json
import uuid

import pytest
import respx
from fastapi import FastAPI
from httpx import AsyncClient
from kombu.exceptions import OperationalError
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings, get_settings
from byop.models import User
from byop.redis_client import get_redis_client
from byop.schemas.discovery import DiscoveryStatus
from byop.services.discovery import DiscoveryRequest
from byop.services.discovery_jobs import create_job, load_job
from byop.tasks import discovery as tasks
from tests.helpers import make_settings
from tests.models.factories import make_connection, make_show, make_user
from tests.providers.llm.helpers import OPENROUTER_URL, completion

pytestmark = pytest.mark.usefixtures("fake_dns")

FEED = "https://news.example.com/rss.xml"
RSS = (
    b'<?xml version="1.0"?><rss version="2.0"><channel><title>Fresh</title>'
    b"<item><title>One</title></item></channel></rss>"
)


def configured() -> Settings:
    return make_settings(
        openrouter_api_key=SecretStr("sk-or-test-key-123456"),
        default_llm_provider="openrouter",
        default_llm_model="vendor/model",
    )


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    """Capture what would be sent to the worker instead of using a broker."""
    sent: list[tuple[object, ...]] = []
    monkeypatch.setattr(tasks.discover_sources_task, "delay", lambda *args: sent.append(args))
    return sent


async def new_show(authed: AsyncClient, **fields: object) -> str:
    body = {"title": "Open AI", "topic": "open-source AI tooling", "language": "de", **fields}
    return str((await authed.post("/api/shows", json=body)).json()["id"])


async def test_discover_queues_a_job_with_the_shows_topic_and_model(
    authed: AsyncClient, queued: list[tuple[object, ...]]
) -> None:
    show_id = await new_show(authed)

    response = await authed.post(f"/api/shows/{show_id}/sources/discover")

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    [(sent_job, _user, sent_show, topic, language, provider, model)] = queued
    assert (sent_job, sent_show, topic, language) == (
        job_id,
        show_id,
        "open-source AI tooling",
        "de",
    )
    assert (provider, model) == (None, None)
    job = (await authed.get(f"/api/sources/discover/{job_id}")).json()
    assert job == {
        "job_id": job_id,
        "status": "queued",
        "show_id": show_id,
        "candidates": [],
        "error": None,
        "warnings": [],
    }


async def test_a_shows_own_model_is_passed_along(
    app: FastAPI, authed: AsyncClient, queued: list[tuple[object, ...]]
) -> None:
    app.dependency_overrides[get_settings] = configured
    show_id = await new_show(authed, llm_provider="openrouter", llm_model="vendor/pick")
    # creating with a model verifies it against the provider; the call is not under test here
    assert show_id

    await authed.post(f"/api/shows/{show_id}/sources/discover")

    assert queued[-1][5:] == ("openrouter", "vendor/pick")


@respx.mock
async def test_the_job_reports_the_result_once_the_worker_is_done(
    app: FastAPI,
    authed: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    queued: list[tuple[object, ...]],
) -> None:
    respx.post(OPENROUTER_URL).respond(
        200,
        json=completion(
            json.dumps(
                {
                    "candidates": [
                        {"kind": "rss", "value": FEED, "name": "News", "reason": "Daily."},
                        {"kind": "web_search", "value": "open ai tooling", "name": "Q"},
                    ]
                }
            )
        ),
    )
    respx.get(FEED).respond(200, content=RSS, headers={"content-type": "application/rss+xml"})
    show_id = await new_show(authed)
    job_id = (await authed.post(f"/api/shows/{show_id}/sources/discover")).json()["job_id"]
    user_id = queued[0][1]

    await tasks.run_discovery_job(
        job_id,
        DiscoveryRequest(uuid.UUID(str(user_id)), uuid.UUID(show_id), "open-source AI tooling"),
        session=db_session,
        redis=get_redis_client(),
        settings=configured(),
    )

    job = (await authed.get(f"/api/sources/discover/{job_id}")).json()
    assert job["status"] == "done" and job["error"] is None
    assert [(c["kind"], c["value"]) for c in job["candidates"]] == [
        ("rss", FEED),
        ("web_search", "open ai tooling"),
    ]
    assert job["candidates"][0]["recent_titles"] == ["One"]


async def test_the_draft_endpoint_works_before_a_show_exists(
    authed: AsyncClient, queued: list[tuple[object, ...]]
) -> None:
    response = await authed.post(
        "/api/sources/discover",
        json={
            "topic": "  home gardening  ",
            "language": "en",
            "llm_provider": "openai",
            "llm_model": "gpt-x",
        },
    )

    assert response.status_code == 202
    [(job_id, _user, show, topic, language, provider, model)] = queued
    assert (show, topic, language, provider, model) == (
        None,
        "home gardening",
        "en",
        "openai",
        "gpt-x",
    )
    job = (await authed.get(f"/api/sources/discover/{job_id}")).json()
    assert job["status"] == "queued" and job["show_id"] is None


@pytest.mark.parametrize(
    "body",
    [{}, {"topic": "   "}, {"topic": "x", "llm_provider": "elevenlabs"}, {"topic": "x" * 5001}],
)
async def test_the_draft_request_is_validated(
    authed: AsyncClient, queued: list[tuple[object, ...]], body: dict[str, object]
) -> None:
    assert (await authed.post("/api/sources/discover", json=body)).status_code == 422
    assert queued == []


async def test_unknown_shows_and_jobs_are_404(authed: AsyncClient) -> None:
    unknown = "00000000-0000-4000-8000-000000000000"

    assert (await authed.post(f"/api/shows/{unknown}/sources/discover")).status_code == 404
    assert (await authed.get("/api/sources/discover/nope")).status_code == 404


async def test_other_users_shows_and_jobs_are_off_limits(
    authed: AsyncClient, db_session: AsyncSession, queued: list[tuple[object, ...]]
) -> None:
    other = await make_user(db_session, "other@example.com")
    theirs = await make_show(db_session, other, slug="theirs")
    their_job = await create_job(get_redis_client(), other.id, theirs.id)

    assert (await authed.post(f"/api/shows/{theirs.id}/sources/discover")).status_code == 404
    assert (await authed.get(f"/api/sources/discover/{their_job}")).status_code == 404
    assert queued == []


async def test_a_broken_queue_is_a_503(
    authed: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object) -> None:
        raise OperationalError("broker down")

    monkeypatch.setattr(tasks.discover_sources_task, "delay", boom)

    response = await authed.post("/api/sources/discover", json={"topic": "x"})

    assert response.status_code == 503


async def test_requires_a_session(client: AsyncClient) -> None:
    show = "00000000-0000-4000-8000-000000000000"

    assert (await client.post(f"/api/shows/{show}/sources/discover")).status_code == 401
    assert (await client.post("/api/sources/discover", json={"topic": "x"})).status_code == 401
    assert (await client.get("/api/sources/discover/abc")).status_code == 401


# --- the worker side ------------------------------------------------------------------------


async def start(user_id: uuid.UUID) -> tuple[str, DiscoveryRequest]:
    request = DiscoveryRequest(user_id, None, "topic")
    return await create_job(get_redis_client(), user_id, None), request


async def test_a_job_without_a_model_fails_with_instructions(
    db_session: AsyncSession, admin_user: User
) -> None:
    user_id = admin_user.id
    job_id, request = await start(user_id)

    await tasks.run_discovery_job(
        job_id, request, session=db_session, redis=get_redis_client(), settings=make_settings()
    )

    record = await load_job(get_redis_client(), job_id)
    assert record is not None
    assert record.status is DiscoveryStatus.FAILED
    assert record.error is not None and "DEFAULT_LLM_PROVIDER" in record.error


@respx.mock
async def test_a_model_error_ends_the_job_as_failed(
    db_session: AsyncSession, admin_user: User
) -> None:
    respx.post(OPENROUTER_URL).respond(401, json={"error": {"message": "bad key"}})
    job_id, request = await start(admin_user.id)

    await tasks.run_discovery_job(
        job_id, request, session=db_session, redis=get_redis_client(), settings=configured()
    )

    record = await load_job(get_redis_client(), job_id)
    assert record is not None and record.status is DiscoveryStatus.FAILED
    assert record.error is not None and "rejected the API key" in record.error


@respx.mock
async def test_other_model_errors_are_reported_as_such(
    db_session: AsyncSession, admin_user: User
) -> None:
    respx.post(OPENROUTER_URL).respond(
        400, json={"error": {"message": "bad request", "code": "invalid_prompt"}}
    )
    job_id, request = await start(admin_user.id)

    await tasks.run_discovery_job(
        job_id, request, session=db_session, redis=get_redis_client(), settings=configured()
    )

    record = await load_job(get_redis_client(), job_id)
    assert record is not None and record.status is DiscoveryStatus.FAILED
    # What the provider said is kept, not replaced by a generic message.
    assert record.error is not None
    assert "HTTP 400" in record.error and "bad request" in record.error


@respx.mock
async def test_an_unexpected_crash_still_ends_the_job(
    db_session: AsyncSession, admin_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(tasks, "discover_sources", boom)
    job_id, request = await start(admin_user.id)

    await tasks.run_discovery_job(
        job_id, request, session=db_session, redis=get_redis_client(), settings=configured()
    )

    record = await load_job(get_redis_client(), job_id)
    assert record is not None and record.status is DiscoveryStatus.FAILED
    assert record.error is not None
    assert record.error.startswith("Discovery failed unexpectedly (RuntimeError: kaboom)")


async def test_an_expired_job_is_ignored(db_session: AsyncSession, admin_user: User) -> None:
    request = DiscoveryRequest(admin_user.id, None, "topic")

    await tasks.run_discovery_job(
        "expired", request, session=db_session, redis=get_redis_client(), settings=configured()
    )

    assert await load_job(get_redis_client(), "expired") is None


async def test_accepted_candidates_are_saved_as_discovered_sources(
    authed: AsyncClient,
) -> None:
    show_id = await new_show(authed)

    response = await authed.post(
        f"/api/shows/{show_id}/sources",
        json={"kind": "web_search", "value": "open ai tooling", "origin": "discovered"},
    )

    assert response.status_code == 201
    assert response.json()["origin"] == "discovered"


# --- web-search pre-check ----------------------------------------------------------------------

MODELS = "https://openrouter.ai/api/v1/models"
CATALOG = {
    "data": [{"id": "vendor/model", "name": "M", "architecture": {"output_modalities": ["text"]}}]
}


async def show_with(
    db_session: AsyncSession,
    user: User,
    provider: str | None,
    model: str | None,
    slug: str = "daily-ai",
) -> str:
    show = await make_show(db_session, user, slug)
    show.llm_provider, show.llm_model = provider, model
    await db_session.flush()
    return str(show.id)


async def test_a_connection_that_cannot_search_is_refused_before_any_job_runs(
    authed: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    queued: list[tuple[object, ...]],
) -> None:
    conn = await make_connection(db_session, admin_user, "Home Ollama")
    show_id = await show_with(db_session, admin_user, f"conn:{conn.id}", "llama3")

    response = await authed.post(f"/api/shows/{show_id}/sources/discover")

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "'llama3'" in detail and "Home Ollama" in detail and "Web search" in detail
    assert queued == []  # nothing was queued


async def test_a_connection_marked_for_web_search_is_accepted(
    authed: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    queued: list[tuple[object, ...]],
) -> None:
    conn = await make_connection(db_session, admin_user, "Sonar box", web_search=True)
    show_id = await show_with(db_session, admin_user, f"conn:{conn.id}", "sonar")

    response = await authed.post(f"/api/shows/{show_id}/sources/discover")

    assert response.status_code == 202 and len(queued) == 1
    assert response.json()["warnings"] == []


async def test_the_wizards_draft_discovery_is_checked_too(
    app: FastAPI, authed: AsyncClient, queued: list[tuple[object, ...]]
) -> None:
    app.dependency_overrides[get_settings] = lambda: make_settings(
        openai_api_key=SecretStr("sk-openai-test-key-123456")
    )
    draft = {"topic": "rust", "llm_provider": "openai"}

    refused = await authed.post("/api/sources/discover", json={**draft, "llm_model": "gpt-4o"})
    accepted = await authed.post(
        "/api/sources/discover", json={**draft, "llm_model": "gpt-4o-search-preview"}
    )

    assert refused.status_code == 422
    assert "'gpt-4o'" in refused.json()["detail"] and "OpenAI" in refused.json()["detail"]
    assert accepted.status_code == 202 and len(queued) == 1


@respx.mock
async def test_an_unconfirmed_capability_is_a_warning_not_a_refusal(
    app: FastAPI, authed: AsyncClient, queued: list[tuple[object, ...]]
) -> None:
    app.dependency_overrides[get_settings] = configured
    respx.get(MODELS).respond(503)

    response = await authed.post(
        "/api/sources/discover",
        json={"topic": "rust", "llm_provider": "openrouter", "llm_model": "vendor/model"},
    )

    assert response.status_code == 202
    [warning] = response.json()["warnings"]
    assert "Could not check whether 'vendor/model' can search the web" in warning
    job = (await authed.get(f"/api/sources/discover/{response.json()['job_id']}")).json()
    assert job["warnings"] == [warning]  # still there when the results are read


@respx.mock
async def test_the_discovery_model_endpoint_says_which_model_and_where_it_comes_from(
    app: FastAPI, authed: AsyncClient
) -> None:
    respx.get(MODELS).respond(200, json=CATALOG)
    app.dependency_overrides[get_settings] = configured

    default = (await authed.get("/api/sources/discover/model")).json()
    shows_own = (
        await authed.get(
            "/api/sources/discover/model",
            params={"llm_provider": "openrouter", "llm_model": "vendor/model"},
        )
    ).json()
    app.dependency_overrides[get_settings] = lambda: make_settings(
        openrouter_api_key=SecretStr("sk-or-test-key-123456"),
        discovery_llm_provider="openrouter",
        discovery_llm_model="perplexity/sonar",
        default_llm_provider="openrouter",
        default_llm_model="vendor/model",
    )
    dedicated = (await authed.get("/api/sources/discover/model")).json()

    assert default == {
        "provider": "openrouter",
        "provider_label": "OpenRouter",
        "model": "vendor/model",
        "source": "default",
        "web_search": "yes",
        "message": None,
    }
    assert shows_own["source"] == "show"
    assert (dedicated["model"], dedicated["source"]) == ("perplexity/sonar", "discovery_setting")


async def test_the_discovery_model_endpoint_reports_a_model_that_cannot_search(
    app: FastAPI, authed: AsyncClient
) -> None:
    app.dependency_overrides[get_settings] = lambda: make_settings(
        openai_api_key=SecretStr("sk-openai-test-key-123456"),
        default_llm_provider="openai",
        default_llm_model="gpt-4o",
    )

    body = (await authed.get("/api/sources/discover/model")).json()

    assert body["web_search"] == "no" and "gpt-4o" in body["message"]


async def test_the_discovery_model_endpoint_is_404_without_any_model(
    app: FastAPI, authed: AsyncClient
) -> None:
    app.dependency_overrides[get_settings] = lambda: make_settings()

    response = await authed.get("/api/sources/discover/model")

    assert response.status_code == 404 and "DEFAULT_LLM_PROVIDER" in response.json()["detail"]


# --- failures at run time ----------------------------------------------------------------------


@respx.mock
@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (
            400,
            {
                "error": {
                    "message": "Provider returned error",
                    "metadata": {"raw": "web plugin unsupported"},
                }
            },
            "refused the web-search request",
        ),
        (402, {"error": {"message": "Insufficient credits"}}, "cannot pay for this request"),
        (
            404,
            {"error": {"message": "No endpoints found for vendor/model"}},
            "does not know the model",
        ),
        (429, {"error": {"message": "rate limited"}}, "rate limiting"),
    ],
)
async def test_a_provider_rejection_shows_the_providers_reason(
    db_session: AsyncSession,
    admin_user: User,
    status: int,
    body: dict[str, object],
    expected: str,
) -> None:
    respx.post(OPENROUTER_URL).respond(status, json=body)
    job_id, request = await start(admin_user.id)

    await tasks.run_discovery_job(
        job_id, request, session=db_session, redis=get_redis_client(), settings=configured()
    )

    record = await load_job(get_redis_client(), job_id)
    assert record is not None and record.status is DiscoveryStatus.FAILED
    assert record.error is not None
    assert expected in record.error and "OpenRouter" in record.error
    assert "The provider said:" in record.error  # the provider's own words, not a generic line


async def test_the_worker_also_refuses_a_model_that_cannot_search(
    db_session: AsyncSession, admin_user: User
) -> None:
    conn = await make_connection(db_session, admin_user, "Plain box")
    job_id, _ = await start(admin_user.id)
    request = DiscoveryRequest(
        admin_user.id, None, "topic", llm_provider=f"conn:{conn.id}", llm_model="llama3"
    )

    await tasks.run_discovery_job(
        job_id, request, session=db_session, redis=get_redis_client(), settings=make_settings()
    )

    record = await load_job(get_redis_client(), job_id)
    assert record is not None and record.status is DiscoveryStatus.FAILED
    assert record.error is not None and "cannot search the web" in record.error


async def test_the_discovery_model_of_a_show_follows_the_show(
    app: FastAPI, authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    conn = await make_connection(db_session, admin_user, "Plain box")
    show_id = await show_with(db_session, admin_user, f"conn:{conn.id}", "llama3")
    other = await make_user(db_session, "other@example.com")
    theirs = await show_with(db_session, other, None, None, "theirs")

    mine = (await authed.get("/api/sources/discover/model", params={"show_id": show_id})).json()
    foreign = await authed.get("/api/sources/discover/model", params={"show_id": theirs})

    assert (mine["provider_label"], mine["model"], mine["source"]) == (
        "Plain box",
        "llama3",
        "show",
    )
    assert mine["web_search"] == "no"
    assert foreign.status_code == 404
