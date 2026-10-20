import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import User
from byop.models.enums import ShowStyle
from byop.services.styles import BUILTINS, builtin_instructions
from tests.models.factories import make_show, make_user

URL = "/api/styles"
GOOD = {"name": "Late-night chat", "description": "Slow and warm.", "instructions": "Keep it calm."}


async def make(authed: AsyncClient, **fields: object) -> dict[str, object]:
    response = await authed.post(URL, json={**GOOD, **fields})
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


# --- listing ---------------------------------------------------------------------------------


async def test_the_built_in_styles_come_first_with_the_instructions_they_give_the_model(
    authed: AsyncClient,
) -> None:
    custom = await make(authed, name="Zed")

    body = (await authed.get(URL)).json()

    assert [s["id"] for s in body[:4]] == [b.key.value for b in BUILTINS]
    assert body[4]["id"] == custom["id"]
    for entry, builtin in zip(body[:4], BUILTINS, strict=True):
        assert entry["kind"] == "builtin" and entry["name"] == builtin.name
        assert entry["description"] and entry["created_at"] is None
        assert entry["instructions"] == builtin_instructions(builtin.key)  # verbatim
    assert "interviewer" in body[3]["instructions"]


async def test_each_style_counts_the_shows_that_use_it(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    custom = await make(authed)
    await make_show(db_session, admin_user, "one")
    other = await make_show(db_session, admin_user, "two")
    other.custom_style_id = uuid.UUID(str(custom["id"]))
    await db_session.flush()

    body = {s["id"]: s for s in (await authed.get(URL)).json()}

    assert body["news_briefing"]["shows_using"] == 1  # the default style of the first show
    assert body[str(custom["id"])]["shows_using"] == 1
    assert body["conversational"]["shows_using"] == 0


async def test_only_your_own_styles_are_listed(
    authed: AsyncClient, db_session: AsyncSession
) -> None:
    other = await make_user(db_session, "other@example.com")
    from byop.models import Style

    db_session.add(Style(user_id=other.id, name="Theirs", instructions="x"))
    await db_session.flush()

    assert [s["kind"] for s in (await authed.get(URL)).json()] == ["builtin"] * 4


# --- create, change, delete -----------------------------------------------------------------


async def test_a_style_can_be_created_changed_and_deleted(authed: AsyncClient) -> None:
    created = await make(authed)
    assert created["kind"] == "custom" and created["shows_using"] == 0
    style_id = created["id"]

    changed = await authed.patch(
        f"{URL}/{style_id}", json={"name": "Slow chat", "instructions": "Take your time."}
    )
    untouched = await authed.patch(f"{URL}/{style_id}", json={"description": "Warm."})

    assert changed.status_code == 200
    assert (changed.json()["name"], changed.json()["instructions"]) == (
        "Slow chat",
        "Take your time.",
    )
    assert untouched.json()["description"] == "Warm."
    assert untouched.json()["name"] == "Slow chat"  # omitted fields keep their value
    assert (await authed.delete(f"{URL}/{style_id}")).status_code == 204
    assert [s["kind"] for s in (await authed.get(URL)).json()] == ["builtin"] * 4


async def test_a_name_can_be_used_once_whatever_the_case(authed: AsyncClient) -> None:
    first = await make(authed, name="Chat")
    second = await make(authed, name="Other")

    duplicate = await authed.post(URL, json={**GOOD, "name": "chat"})
    renamed = await authed.patch(f"{URL}/{second['id']}", json={"name": "CHAT"})
    same = await authed.patch(f"{URL}/{first['id']}", json={"name": "Chat"})

    assert duplicate.status_code == 409 and "already a style called" in duplicate.json()["detail"]
    assert renamed.status_code == 409
    assert same.status_code == 200  # keeping its own name is fine


@pytest.mark.parametrize(
    "fields",
    [
        {"name": ""},
        {"name": " " * 5},
        {"name": "x" * 101},
        {"instructions": ""},
        {"instructions": "x" * 20001},
        {"description": "x" * 501},
    ],
)
async def test_the_fields_are_checked(authed: AsyncClient, fields: dict[str, str]) -> None:
    assert (await authed.post(URL, json={**GOOD, **fields})).status_code == 422


async def test_instructions_that_cannot_be_used_are_refused_with_the_reason(
    authed: AsyncClient,
) -> None:
    created = await make(authed)
    bad = {
        "unfinished": "Open with {% if speakers %} no end",
        "unknown placeholder": "Talk about {{ nothing_like_this }}.",
        "sandbox": "{{ ''.__class__.__mro__ }}",
        "huge": "{{ 'x' * 100000 }}",
    }

    for label, text in bad.items():
        made = await authed.post(URL, json={**GOOD, "name": label, "instructions": text})
        patched = await authed.patch(f"{URL}/{created['id']}", json={"instructions": text})
        for response in (made, patched):
            assert response.status_code == 422, label
            [problem] = response.json()["detail"]
            assert problem["loc"] == ["body", "instructions"]
            assert "cannot be used as they are" in problem["msg"] or "too long" in problem["msg"]


async def test_placeholders_of_the_prompt_may_be_used(authed: AsyncClient) -> None:
    text = (
        "Open with {{ speakers[0].name }} on {{ topic }}."
        "{% if speakers|length > 1 %} Chat.{% endif %}"
    )

    assert (await authed.post(URL, json={**GOOD, "instructions": text})).status_code == 201


async def test_a_style_in_use_cannot_be_deleted_and_the_message_names_the_shows(
    authed: AsyncClient,
) -> None:
    style = await make(authed)
    for title in ("Alpha", "Beta"):
        shown = await authed.post(
            "/api/shows", json={"title": title, "topic": "t", "custom_style_id": style["id"]}
        )
        assert shown.status_code == 201

    response = await authed.delete(f"{URL}/{style['id']}")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "used by 2 show(s)" in detail and "'Alpha'" in detail and "'Beta'" in detail
    assert (await authed.get(URL)).json()[4]["shows_using"] == 2


async def test_someone_elses_style_is_not_found(
    authed: AsyncClient, db_session: AsyncSession
) -> None:
    from byop.models import Style

    other = await make_user(db_session, "other@example.com")
    theirs = Style(user_id=other.id, name="Theirs", instructions="x")
    db_session.add(theirs)
    await db_session.flush()

    assert (await authed.patch(f"{URL}/{theirs.id}", json={"name": "Mine"})).status_code == 404
    assert (await authed.delete(f"{URL}/{theirs.id}")).status_code == 404
    assert (await authed.patch(f"{URL}/{uuid.uuid4()}", json={"name": "x"})).status_code == 404


async def test_requires_a_session(client: AsyncClient) -> None:
    assert (await client.get(URL)).status_code == 401
    assert (await client.post(URL, json=GOOD)).status_code == 401
    assert (await client.patch(f"{URL}/{uuid.uuid4()}", json={})).status_code == 401
    assert (await client.delete(f"{URL}/{uuid.uuid4()}")).status_code == 401


# --- on shows ---------------------------------------------------------------------------------


async def test_a_show_can_use_a_custom_style_and_go_back_to_a_built_in(authed: AsyncClient) -> None:
    style = await make(authed)

    created = await authed.post(
        "/api/shows", json={"title": "Mine", "topic": "t", "custom_style_id": style["id"]}
    )
    show_id = created.json()["id"]
    assert created.status_code == 201 and created.json()["custom_style_id"] == style["id"]

    plain = await authed.post("/api/shows", json={"title": "Plain", "topic": "t"})
    assert plain.json()["custom_style_id"] is None  # existing kinds of shows are unchanged

    builtin = await authed.patch(f"/api/shows/{show_id}", json={"style": "deep_dive"})
    assert (builtin.json()["style"], builtin.json()["custom_style_id"]) == ("deep_dive", None)

    again = await authed.patch(f"/api/shows/{show_id}", json={"custom_style_id": style["id"]})
    assert again.json()["custom_style_id"] == style["id"]
    cleared = await authed.patch(f"/api/shows/{show_id}", json={"custom_style_id": None})
    assert cleared.status_code == 200 and cleared.json()["custom_style_id"] is None
    assert cleared.json()["style"] == "deep_dive"


async def test_a_show_cannot_name_both_kinds_of_style(authed: AsyncClient) -> None:
    style = await make(authed)
    both = {"style": "interview", "custom_style_id": style["id"]}

    assert (
        await authed.post("/api/shows", json={"title": "x", "topic": "t", **both})
    ).status_code == 422
    show = await authed.post("/api/shows", json={"title": "y", "topic": "t"})
    assert (await authed.patch(f"/api/shows/{show.json()['id']}", json=both)).status_code == 422


async def test_a_show_cannot_use_a_style_that_is_not_yours(
    authed: AsyncClient, db_session: AsyncSession
) -> None:
    from byop.models import Style

    other = await make_user(db_session, "other@example.com")
    theirs = Style(user_id=other.id, name="Theirs", instructions="x")
    db_session.add(theirs)
    await db_session.flush()
    show = await authed.post("/api/shows", json={"title": "y", "topic": "t"})

    created = await authed.post(
        "/api/shows", json={"title": "x", "topic": "t", "custom_style_id": str(theirs.id)}
    )
    updated = await authed.patch(
        f"/api/shows/{show.json()['id']}", json={"custom_style_id": str(theirs.id)}
    )
    missing = await authed.patch(
        f"/api/shows/{show.json()['id']}", json={"custom_style_id": str(uuid.uuid4())}
    )

    for response in (created, updated, missing):
        assert response.status_code == 422
        assert "style does not exist" in str(response.json()["detail"])


async def test_every_built_in_style_is_still_accepted(authed: AsyncClient) -> None:
    for style in ShowStyle:
        response = await authed.post(
            "/api/shows", json={"title": f"Show {style.value}", "topic": "t", "style": style.value}
        )
        assert response.status_code == 201 and response.json()["style"] == style.value
