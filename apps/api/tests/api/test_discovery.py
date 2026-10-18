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
from tests.models.factories import make_show, make_user
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
    respx.post(OPENROUTER_URL).respond(400, json={"error": {"message": "bad request"}})
    job_id, request = await start(admin_user.id)

    await tasks.run_discovery_job(
        job_id, request, session=db_session, redis=get_redis_client(), settings=configured()
    )

    record = await load_job(get_redis_client(), job_id)
    assert record is not None and record.status is DiscoveryStatus.FAILED
    assert record.error is not None and "language model failed" in record.error


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
    assert record.error == "Discovery failed unexpectedly."


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
