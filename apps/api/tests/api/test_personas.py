import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Persona, Speaker, User
from byop.services.personas import STARTER_PERSONAS, seed_starter_personas
from tests.models.factories import make_show, make_user

URL = "/api/personas"
GOOD = {"name": "Night host", "persona": "Quiet, warm and a little sleepy."}


async def make(authed: AsyncClient, **fields: object) -> dict[str, object]:
    response = await authed.post(URL, json={**GOOD, **fields})
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


# --- the library -----------------------------------------------------------------------------


async def test_the_library_starts_empty_until_starters_are_seeded(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    assert (await authed.get(URL)).json() == []

    await seed_starter_personas(db_session, admin_user.id)
    body = (await authed.get(URL)).json()

    assert [p["name"] for p in body] == sorted((n for n, _ in STARTER_PERSONAS), key=str.lower)
    assert len(body) == 5 and all(p["persona"] and p["tts_provider"] is None for p in body)


async def test_seeding_never_makes_duplicates_and_leaves_edits_alone(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    await seed_starter_personas(db_session, admin_user.id)
    mine = (await authed.get(URL)).json()[0]
    await authed.patch(f"{URL}/{mine['id']}", json={"persona": "Rewritten."})

    await seed_starter_personas(db_session, admin_user.id)

    body = (await authed.get(URL)).json()
    assert len(body) == len(STARTER_PERSONAS)
    assert next(p for p in body if p["id"] == mine["id"])["persona"] == "Rewritten."


async def test_every_starter_can_be_deleted(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    await seed_starter_personas(db_session, admin_user.id)

    for persona in (await authed.get(URL)).json():
        assert (await authed.delete(f"{URL}/{persona['id']}")).status_code == 204

    assert (await authed.get(URL)).json() == []


# --- create, change, delete -----------------------------------------------------------------


async def test_a_persona_can_be_created_changed_and_deleted(authed: AsyncClient) -> None:
    created = await make(authed)
    assert created["tts_provider"] is None and created["voice_params"] == {}
    persona_id = created["id"]

    changed = await authed.patch(
        f"{URL}/{persona_id}", json={"name": "Late host", "persona": "Sleepier."}
    )

    assert changed.status_code == 200
    assert (changed.json()["name"], changed.json()["persona"]) == ("Late host", "Sleepier.")
    assert [p["name"] for p in (await authed.get(URL)).json()] == ["Late host"]
    assert (await authed.delete(f"{URL}/{persona_id}")).status_code == 204
    assert (await authed.get(URL)).json() == []


async def test_a_persona_may_carry_a_default_voice(authed: AsyncClient) -> None:
    created = await make(
        authed, tts_provider="openrouter", voice_id="af_bella", voice_params={"model": "m/x"}
    )

    assert (created["tts_provider"], created["voice_id"]) == ("openrouter", "af_bella")
    assert created["voice_params"] == {"model": "m/x"}
    changed = await authed.patch(f"{URL}/{created['id']}", json={"voice_id": "af_heart"})
    assert changed.json()["voice_id"] == "af_heart"
    assert changed.json()["voice_params"] == {"model": "m/x"}  # untouched
    removed = await authed.patch(
        f"{URL}/{created['id']}", json={"tts_provider": None, "voice_id": None}
    )
    assert removed.status_code == 200
    assert removed.json()["tts_provider"] is None and removed.json()["voice_params"] == {}


@pytest.mark.parametrize(
    "fields",
    [
        {"tts_provider": "openai"},  # a provider without a voice
        {"voice_id": "alloy"},  # a voice without a provider
        {"voice_params": {"model": "x"}},  # settings without a voice
        {"tts_provider": "nope", "voice_id": "a"},
        {"tts_provider": "kokoro", "voice_id": "af_bella", "voice_params": {"nope": 1}},
        {"tts_provider": "openai", "voice_id": "alloy", "voice_params": {"speed": 99}},
        {"tts_provider": "openrouter", "voice_id": "alloy"},  # OpenRouter needs a model
    ],
)
async def test_a_default_voice_must_be_complete_and_valid(
    authed: AsyncClient, fields: dict[str, object]
) -> None:
    assert (await authed.post(URL, json={**GOOD, **fields})).status_code == 422


@pytest.mark.parametrize(
    "fields",
    [
        {"name": ""},
        {"name": "x" * 101},
        {"persona": ""},
        {"persona": "x" * 2001},
    ],
)
async def test_the_text_fields_are_checked(authed: AsyncClient, fields: dict[str, str]) -> None:
    assert (await authed.post(URL, json={**GOOD, **fields})).status_code == 422


async def test_a_name_can_be_used_once_whatever_the_case(authed: AsyncClient) -> None:
    first = await make(authed, name="Host")
    second = await make(authed, name="Other")

    duplicate = await authed.post(URL, json={**GOOD, "name": "HOST"})
    renamed = await authed.patch(f"{URL}/{second['id']}", json={"name": "host"})
    same = await authed.patch(f"{URL}/{first['id']}", json={"name": "Host"})

    assert duplicate.status_code == 409 and "already a persona called" in duplicate.json()["detail"]
    assert renamed.status_code == 409 and same.status_code == 200


async def test_editing_or_deleting_a_persona_does_not_change_speakers_that_used_it(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    persona = await make(authed, persona="The original text.")
    show = await make_show(db_session, admin_user)
    db_session.add(
        Speaker(
            user_id=admin_user.id,
            show_id=show.id,
            position=0,
            name="Alex",
            persona="The original text.",  # copied when the persona was applied
            tts_provider="kokoro",
            voice_id="af_bella",
        )
    )
    await db_session.flush()

    await authed.patch(f"{URL}/{persona['id']}", json={"persona": "Changed completely."})
    await authed.delete(f"{URL}/{persona['id']}")

    speaker = await db_session.scalar(select(Speaker).where(Speaker.show_id == show.id))
    assert speaker is not None and speaker.persona == "The original text."


async def test_personas_belong_to_their_user(authed: AsyncClient, db_session: AsyncSession) -> None:
    other = await make_user(db_session, "other@example.com")
    theirs = Persona(user_id=other.id, name="Theirs", persona="x")
    db_session.add(theirs)
    await db_session.flush()
    await make(authed)

    assert [p["name"] for p in (await authed.get(URL)).json()] == ["Night host"]
    assert (await authed.patch(f"{URL}/{theirs.id}", json={"name": "Mine"})).status_code == 404
    assert (await authed.delete(f"{URL}/{theirs.id}")).status_code == 404
    assert (await authed.patch(f"{URL}/{uuid.uuid4()}", json={"name": "x"})).status_code == 404
    # The same name under another user is fine.
    assert (await authed.post(URL, json={**GOOD, "name": "Theirs"})).status_code == 201


async def test_requires_a_session(client: AsyncClient) -> None:
    assert (await client.get(URL)).status_code == 401
    assert (await client.post(URL, json=GOOD)).status_code == 401
    assert (await client.patch(f"{URL}/{uuid.uuid4()}", json={})).status_code == 401
    assert (await client.delete(f"{URL}/{uuid.uuid4()}")).status_code == 401
