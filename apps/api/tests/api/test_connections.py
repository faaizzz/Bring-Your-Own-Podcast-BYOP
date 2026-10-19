import uuid

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import User
from tests.models.factories import make_connection, make_show, make_user

API_KEY = "sk-conn-secret-0123456789"
HEADER_VALUE = "gateway-token-abcdef123456"
BODY = {
    "name": "Ollama",
    "base_url": "http://ollama:11434/v1/",
    "api_key": API_KEY,
    "headers": [{"name": "X-Gateway-Token", "value": HEADER_VALUE}],
}


async def create(authed: AsyncClient, **overrides: object) -> dict[str, object]:
    response = await authed.post("/api/connections", json={**BODY, **overrides})
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


# --- create / read ------------------------------------------------------------------------------


async def test_a_connection_is_created_and_every_secret_is_masked(authed: AsyncClient) -> None:
    created = await create(authed)

    assert created["name"] == "Ollama"
    assert created["base_url"] == "http://ollama:11434/v1"
    assert (created["llm"], created["tts"], created["web_search"]) == (True, False, False)
    assert created["api_key_masked"] == "sk-…6789"
    assert created["headers"] == [{"name": "X-Gateway-Token", "value_masked": "gat…3456"}]
    for response in (
        await authed.get("/api/connections"),
        await authed.get(f"/api/connections/{created['id']}"),
    ):
        assert API_KEY not in response.text and HEADER_VALUE not in response.text


async def test_the_secrets_are_stored_encrypted(
    authed: AsyncClient, db_session: AsyncSession
) -> None:
    from sqlalchemy import select

    from byop.models import ProviderConnection

    await create(authed)

    stored = (await db_session.scalars(select(ProviderConnection))).one()
    assert API_KEY not in stored.secret_encrypted and HEADER_VALUE not in stored.secret_encrypted


async def test_names_are_unique_per_user_ignoring_case(
    authed: AsyncClient, db_session: AsyncSession
) -> None:
    await create(authed)

    again = await authed.post("/api/connections", json={**BODY, "name": "ollama"})

    assert again.status_code == 409
    other = await make_user(db_session, "other@example.com")
    await make_connection(db_session, other, "Ollama")  # another user may use the name
    assert (await authed.get("/api/connections")).status_code == 200


@pytest.mark.parametrize(
    "patch",
    [
        {"headers": [{"name": "Host", "value": "evil"}]},
        {"headers": [{"name": "bad name", "value": "x"}]},
        {"headers": [{"name": "A", "value": "1"}, {"name": "a", "value": "2"}]},
        {"headers": [{"name": "A"}]},  # a new header needs a value
        {"llm": False},  # at least one use
        {"base_url": "ftp://x.example"},
        {"name": " "},
    ],
)
async def test_invalid_connections_are_rejected(
    authed: AsyncClient, patch: dict[str, object]
) -> None:
    response = await authed.post("/api/connections", json={**BODY, **patch})

    assert response.status_code == 422


async def test_connections_are_private_to_their_user(
    authed: AsyncClient, db_session: AsyncSession
) -> None:
    other = await make_user(db_session, "other@example.com")
    foreign = await make_connection(db_session, other, "Theirs")

    assert (await authed.get("/api/connections")).json() == []
    assert (await authed.get(f"/api/connections/{foreign.id}")).status_code == 404
    assert (
        await authed.patch(f"/api/connections/{foreign.id}", json={"enabled": False})
    ).status_code == 404
    assert (await authed.delete(f"/api/connections/{foreign.id}")).status_code == 404
    assert (await authed.post(f"/api/connections/{foreign.id}/test")).status_code == 404


# --- update -------------------------------------------------------------------------------------


@respx.mock
async def test_an_update_keeps_secrets_it_does_not_mention(authed: AsyncClient) -> None:
    created = await create(authed)
    route = respx.get("http://ollama:11434/v1/models").respond(200, json={"data": []})

    changed = await authed.patch(
        f"/api/connections/{created['id']}",
        json={"name": "Ollama 2", "headers": [{"name": "x-gateway-token"}]},
    )
    await authed.post(f"/api/connections/{created['id']}/test")

    assert changed.status_code == 200 and changed.json()["name"] == "Ollama 2"
    sent = route.calls.last.request.headers
    assert sent["x-gateway-token"] == HEADER_VALUE  # the stored value was kept
    assert sent["authorization"] == f"Bearer {API_KEY}"  # so was the key


@respx.mock
async def test_headers_and_key_can_be_replaced_and_removed(authed: AsyncClient) -> None:
    created = await create(authed)
    route = respx.get("http://ollama:11434/v1/models").respond(200, json={"data": []})

    await authed.patch(
        f"/api/connections/{created['id']}",
        json={"api_key": "", "headers": [{"name": "X-Other", "value": "new-value-123456"}]},
    )
    await authed.post(f"/api/connections/{created['id']}/test")

    sent = route.calls.last.request.headers
    assert sent["x-other"] == "new-value-123456"
    assert "x-gateway-token" not in sent and "authorization" not in sent
    assert (await authed.get(f"/api/connections/{created['id']}")).json()["api_key_masked"] is None


async def test_a_header_without_a_stored_value_needs_one(authed: AsyncClient) -> None:
    created = await create(authed)

    response = await authed.patch(
        f"/api/connections/{created['id']}", json={"headers": [{"name": "X-New"}]}
    )

    assert response.status_code == 422


async def test_renaming_onto_another_connection_conflicts(authed: AsyncClient) -> None:
    await create(authed, name="One")
    two = await create(authed, name="Two")

    response = await authed.patch(f"/api/connections/{two['id']}", json={"name": "one"})

    assert response.status_code == 409


# --- deleting a connection in use ----------------------------------------------------------------


async def test_a_connection_in_use_cannot_be_deleted_or_switched_off(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    from byop.models import Speaker

    conn = await make_connection(db_session, admin_user, "Voices", tts=True, llm=False)
    show = await make_show(db_session, admin_user)
    show.llm_provider, show.llm_model = f"conn:{uuid.uuid4()}", "m"
    db_session.add(
        Speaker(
            user_id=admin_user.id, show_id=show.id, position=0, name="Alex",
            tts_provider=f"conn:{conn.id}", voice_id="v",
        )
    )  # fmt: skip
    await db_session.flush()

    listed = (await authed.get("/api/connections")).json()[0]
    assert (listed["shows_using"], listed["speakers_using"]) == (0, 1)
    refused = await authed.delete(f"/api/connections/{conn.id}")
    assert refused.status_code == 409 and "1 speaker" in refused.json()["detail"]
    for patch in ({"enabled": False}, {"tts": False, "llm": True}):
        assert (await authed.patch(f"/api/connections/{conn.id}", json=patch)).status_code == 409

    await db_session.delete(await db_session.get(Speaker, (await _speaker_id(db_session, show.id))))
    await db_session.flush()
    assert (await authed.delete(f"/api/connections/{conn.id}")).status_code == 204
    assert (await authed.get("/api/connections")).json() == []


async def _speaker_id(session: AsyncSession, show_id: uuid.UUID) -> uuid.UUID:
    from sqlalchemy import select

    from byop.models import Speaker

    return (await session.scalars(select(Speaker.id).where(Speaker.show_id == show_id))).one()


# --- test endpoint ------------------------------------------------------------------------------


@respx.mock
async def test_the_test_lists_models_and_voices_and_sends_the_custom_headers(
    authed: AsyncClient,
) -> None:
    created = await create(authed, llm=True, tts=True)
    models = respx.get("http://ollama:11434/v1/models").respond(
        200, json={"data": [{"id": "llama3"}, {"id": "qwen"}]}
    )
    voices = respx.get("http://ollama:11434/v1/audio/voices").respond(
        200, json={"voices": ["af_bella", "am_michael"]}
    )

    result = (await authed.post(f"/api/connections/{created['id']}/test")).json()

    assert result["ok"] is True
    assert [(c["capability"], c["ok"]) for c in result["checks"]] == [("llm", True), ("tts", True)]
    assert (
        "2 models" in result["checks"][0]["detail"] and "2 voices" in result["checks"][1]["detail"]
    )
    for route in (models, voices):
        headers = route.calls.last.request.headers
        assert headers["x-gateway-token"] == HEADER_VALUE
        assert headers["authorization"] == f"Bearer {API_KEY}"
    assert API_KEY not in str(result) and HEADER_VALUE not in str(result)


@respx.mock
async def test_the_test_only_checks_what_is_enabled(authed: AsyncClient) -> None:
    created = await create(authed, llm=False, tts=True)
    voices = respx.get("http://ollama:11434/v1/audio/voices").respond(200, json={"voices": []})

    result = (await authed.post(f"/api/connections/{created['id']}/test")).json()

    assert [c["capability"] for c in result["checks"]] == ["tts"] and voices.called


@respx.mock
@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "Authentication failed (HTTP 401)"), (500, "Unexpected response (HTTP 500)")],
)
async def test_failed_tests_explain_why_without_leaking(
    authed: AsyncClient, status: int, expected: str
) -> None:
    created = await create(authed)
    respx.get("http://ollama:11434/v1/models").respond(status, text=f"{API_KEY} {HEADER_VALUE}")

    result = (await authed.post(f"/api/connections/{created['id']}/test")).json()

    assert result["ok"] is False and result["detail"] == expected
    assert API_KEY not in str(result) and HEADER_VALUE not in str(result)


@respx.mock
async def test_a_server_without_a_list_route_is_reachable_but_unlisted(
    authed: AsyncClient,
) -> None:
    created = await create(authed)
    respx.get("http://ollama:11434/v1/models").respond(404)

    result = (await authed.post(f"/api/connections/{created['id']}/test")).json()

    assert result["ok"] is True and "type the name by hand" in result["checks"][0]["detail"]


@respx.mock
async def test_unreachable_servers_are_reported(authed: AsyncClient) -> None:
    created = await create(authed)
    respx.get("http://ollama:11434/v1/models").mock(side_effect=httpx.ConnectError("boom"))

    result = (await authed.post(f"/api/connections/{created['id']}/test")).json()

    assert result == {
        "ok": False,
        "detail": "Could not connect (ConnectError)",
        "checks": [
            {"capability": "llm", "ok": False, "detail": "Could not connect (ConnectError)"}
        ],
    }
