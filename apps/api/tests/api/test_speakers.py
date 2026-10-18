from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import get_settings
from byop.models import Speaker
from tests.helpers import make_settings
from tests.models.factories import make_show, make_user

Body = list[dict[str, object]]


def configure(app: FastAPI, **overrides: object) -> None:
    app.dependency_overrides[get_settings] = lambda: make_settings(**overrides)


def speaker(name: str, **fields: object) -> dict[str, object]:
    return {"name": name, "tts_provider": "openai", "voice_id": "alloy", **fields}


async def new_show(authed: AsyncClient) -> str:
    response = await authed.post("/api/shows", json={"title": "Daily AI", "topic": "AI"})
    assert response.status_code == 201
    return str(response.json()["id"])


def locations(response_json: object) -> set[tuple[object, ...]]:
    assert isinstance(response_json, dict)
    return {tuple(item["loc"]) for item in response_json["detail"]}


# --- defaults ---------------------------------------------------------------


async def test_new_shows_get_two_hosts_on_the_fallback_provider(authed: AsyncClient) -> None:
    show_id = await new_show(authed)

    response = await authed.get(f"/api/shows/{show_id}/speakers")

    assert response.status_code == 200
    hosts = response.json()
    assert [(h["position"], h["name"], h["tts_provider"]) for h in hosts] == [
        (0, "Alex", "kokoro"),
        (1, "Sam", "kokoro"),
    ]
    assert hosts[0]["voice_id"] != hosts[1]["voice_id"]
    assert all(h["persona"] for h in hosts)


async def test_default_hosts_follow_the_default_tts_provider(
    app: FastAPI, authed: AsyncClient
) -> None:
    configure(app, elevenlabs_api_key=SecretStr("xi-env-key-0123456789"))
    eleven = await authed.get(f"/api/shows/{await new_show(authed)}/speakers")
    configure(app, openai_api_key=SecretStr("sk-env-key-0123456789"))
    openai = await authed.get(f"/api/shows/{await new_show(authed)}/speakers")
    configure(app, openrouter_api_key=SecretStr("sk-or-env-key-123456"))
    openrouter = await authed.get(f"/api/shows/{await new_show(authed)}/speakers")

    assert {h["tts_provider"] for h in eleven.json()} == {"elevenlabs"}
    assert {h["tts_provider"] for h in openai.json()} == {"openai"}
    assert {h["tts_provider"] for h in openrouter.json()} == {"openrouter"}
    # OpenRouter has no default speech model, so the hosts carry one.
    assert all("model" in h["voice_params"] for h in openrouter.json())


# --- replace ----------------------------------------------------------------


async def test_put_replaces_the_ordered_list_and_keeps_ids_by_position(
    authed: AsyncClient,
) -> None:
    show_id = await new_show(authed)
    url = f"/api/shows/{show_id}/speakers"
    before = (await authed.get(url)).json()

    saved = await authed.put(
        url,
        json=[
            speaker("Nova", persona="  Lead  ", voice_params={"speed": 1.1, "model": "tts-1"}),
            speaker(
                "Ruby", tts_provider="elevenlabs", voice_id="abc", voice_params={"stability": 0.4}
            ),
            speaker("Max", fallback_tts_provider="openai", fallback_voice_id="onyx"),
        ],
    )

    assert saved.status_code == 200
    body = saved.json()
    assert [(s["position"], s["name"]) for s in body] == [(0, "Nova"), (1, "Ruby"), (2, "Max")]
    assert body[0]["persona"] == "Lead"
    assert body[0]["voice_params"] == {"speed": 1.1, "model": "tts-1"}
    assert body[1]["voice_params"] == {"stability": 0.4}
    assert body[2]["fallback_voice_id"] == "onyx"
    assert [b["id"] for b in body[:2]] == [b["id"] for b in before]
    assert (await authed.get(url)).json() == body


async def test_put_with_fewer_speakers_removes_the_rest(
    authed: AsyncClient, db_session: AsyncSession
) -> None:
    show_id = await new_show(authed)
    url = f"/api/shows/{show_id}/speakers"

    response = await authed.put(url, json=[speaker("Solo")])

    assert [s["name"] for s in response.json()] == ["Solo"]
    count = await db_session.scalar(select(func.count()).select_from(Speaker))
    assert count == 1


async def test_put_can_reorder_and_swap_names(authed: AsyncClient) -> None:
    url = f"/api/shows/{await new_show(authed)}/speakers"

    response = await authed.put(url, json=[speaker("Sam"), speaker("Alex")])

    assert response.status_code == 200
    assert [s["name"] for s in response.json()] == ["Sam", "Alex"]


async def test_speaker_count_must_be_one_to_four(authed: AsyncClient) -> None:
    url = f"/api/shows/{await new_show(authed)}/speakers"

    assert (await authed.put(url, json=[])).status_code == 422
    five = [speaker(f"Host {n}") for n in range(5)]
    assert (await authed.put(url, json=five)).status_code == 422
    four = [speaker(f"Host {n}") for n in range(4)]
    assert (await authed.put(url, json=four)).status_code == 200


# --- validation ---------------------------------------------------------------


async def test_names_must_be_unique_ignoring_case(authed: AsyncClient) -> None:
    url = f"/api/shows/{await new_show(authed)}/speakers"

    response = await authed.put(url, json=[speaker("Alex"), speaker("ALEX "), speaker("Sam")])

    assert response.status_code == 422
    assert locations(response.json()) == {("body", 1, "name")}
    assert "unique" in response.json()["detail"][0]["msg"]


async def test_errors_point_at_the_exact_field(authed: AsyncClient) -> None:
    url = f"/api/shows/{await new_show(authed)}/speakers"

    response = await authed.put(
        url,
        json=[
            speaker("A", voice_params={"speed": 9, "bogus": 1}),
            speaker("B", tts_provider="elevenlabs", voice_params={"stability": 2, "seed": 1.5}),
            speaker("C", tts_provider="openrouter"),  # needs a model
            speaker("D", fallback_tts_provider="openai"),  # half a fallback
            speaker("E", fallback_tts_provider="openrouter", fallback_voice_id="alloy"),
        ],
    )

    assert response.status_code == 422  # five speakers is also too many, reported by FastAPI
    four = [
        speaker("A", voice_params={"speed": 9, "bogus": 1}),
        speaker("B", tts_provider="elevenlabs", voice_params={"stability": 2, "seed": 1.5}),
        speaker("C", tts_provider="openrouter"),
        speaker("D", fallback_tts_provider="openai"),
    ]
    response = await authed.put(url, json=four)
    assert response.status_code == 422
    found = {tuple(item["loc"]): item["msg"] for item in response.json()["detail"]}
    assert found[("body", 0, "voice_params", "speed")] == "must be at most 4"
    assert found[("body", 0, "voice_params", "bogus")] == "is not supported by this provider"
    assert found[("body", 1, "voice_params", "stability")] == "must be at most 1"
    assert found[("body", 1, "voice_params", "seed")] == "must be a whole number"
    assert found[("body", 2, "voice_params", "model")] == "is required for this provider"
    assert found[("body", 3, "fallback_voice_id")] == "A fallback needs both a provider and a voice"


async def test_a_fallback_cannot_need_voice_parameters(authed: AsyncClient) -> None:
    url = f"/api/shows/{await new_show(authed)}/speakers"

    response = await authed.put(
        url,
        json=[speaker("E", fallback_tts_provider="openrouter", fallback_voice_id="alloy")],
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", 0, "fallback_tts_provider"]


async def test_basic_shape_errors_come_from_the_schema(authed: AsyncClient) -> None:
    url = f"/api/shows/{await new_show(authed)}/speakers"

    for bad in (
        {"name": "", "tts_provider": "openai", "voice_id": "alloy"},
        {"name": "A", "tts_provider": "nope", "voice_id": "alloy"},
        {"name": "A", "tts_provider": "openai", "voice_id": ""},
        {"name": "A", "tts_provider": "openai", "voice_id": "alloy", "voice_params": {"x": [1]}},
    ):
        assert (await authed.put(url, json=[bad])).status_code == 422, bad


# --- ownership ----------------------------------------------------------------


async def test_other_users_speakers_are_off_limits(
    authed: AsyncClient, db_session: AsyncSession
) -> None:
    other = await make_user(db_session, "other@example.com")
    theirs = await make_show(db_session, other, slug="theirs")

    assert (await authed.get(f"/api/shows/{theirs.id}/speakers")).status_code == 404
    put = await authed.put(f"/api/shows/{theirs.id}/speakers", json=[speaker("Mine")])
    assert put.status_code == 404
    count = await db_session.scalar(select(func.count()).select_from(Speaker))
    assert count == 0


async def test_requires_a_session(client: AsyncClient) -> None:
    url = "/api/shows/00000000-0000-4000-8000-000000000000/speakers"
    assert (await client.get(url)).status_code == 401
    assert (await client.put(url, json=[])).status_code == 401


async def test_the_wizard_can_fetch_the_default_hosts_before_a_show_exists(
    app: FastAPI, authed: AsyncClient
) -> None:
    kokoro = await authed.get("/api/voices/default-speakers")
    configure(app, openai_api_key=SecretStr("sk-env-key-0123456789"))
    openai = await authed.get("/api/voices/default-speakers")

    assert [(s["name"], s["tts_provider"]) for s in kokoro.json()] == [
        ("Alex", "kokoro"),
        ("Sam", "kokoro"),
    ]
    assert {s["tts_provider"] for s in openai.json()} == {"openai"}
    assert openai.json()[0]["voice_params"] == {}
