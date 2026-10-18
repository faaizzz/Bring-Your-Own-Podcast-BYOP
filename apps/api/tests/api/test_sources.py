import httpx
import pytest
import respx
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import get_settings
from byop.models import Source
from byop.models.enums import SourceOrigin
from byop.services import safe_http
from byop.services.safe_http import FetchError
from tests.helpers import make_settings
from tests.models.factories import make_show, make_user

FEED = "https://news.example.com/rss.xml"
RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Example News</title>
<item><title>One</title></item><item><title>Two</title></item>
<item><title>Three</title></item><item><title>Four</title></item></channel></rss>"""
HOSTS = {"news.example.com": ["93.184.216.34"], "lan.example": ["192.168.1.9"]}


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(host: str, port: int) -> list[str]:
        if host in HOSTS:
            return HOSTS[host]
        if host.replace(".", "").isdigit():
            return [host]
        raise FetchError(f"Could not find the host '{host}'")

    monkeypatch.setattr(safe_http, "resolve_host", resolve)


def serve_feed(content: bytes = RSS, content_type: str = "application/rss+xml") -> respx.Route:
    return respx.get(FEED).respond(200, content=content, headers={"content-type": content_type})


async def new_show(authed: AsyncClient) -> str:
    response = await authed.post("/api/shows", json={"title": "Daily AI", "topic": "AI"})
    return str(response.json()["id"])


async def add(authed: AsyncClient, show_id: str, **fields: object) -> httpx.Response:
    body = {"kind": "rss", "value": FEED, **fields}
    return await authed.post(f"/api/shows/{show_id}/sources", json=body)


# --- create -------------------------------------------------------------------------------


@respx.mock
async def test_adding_an_rss_feed_validates_it_and_names_it_after_the_feed(
    authed: AsyncClient,
) -> None:
    serve_feed()
    show_id = await new_show(authed)

    response = await add(authed, show_id)

    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "rss" and body["value"] == FEED
    assert body["name"] == "Example News"
    assert body["origin"] == "user" and body["enabled"] is True
    assert body["last_fetched_at"] is None and body["last_error"] is None
    assert body["show_id"] == show_id


@respx.mock
async def test_a_given_name_wins_over_the_feed_title(authed: AsyncClient) -> None:
    serve_feed()

    response = await add(authed, await new_show(authed), name="  My news  ", enabled=False)

    assert response.json()["name"] == "My news"
    assert response.json()["enabled"] is False


@pytest.mark.parametrize(
    ("content", "content_type", "reason"),
    [
        pytest.param(b"<html><body>hi</body></html>", "text/html", "web page", id="html"),
        pytest.param(b"hello", "text/plain", "not a valid RSS or Atom feed", id="text"),
        pytest.param(b"", "application/xml", "not a valid RSS or Atom feed", id="empty"),
    ],
)
@respx.mock
async def test_an_invalid_feed_is_rejected_with_the_reason(
    authed: AsyncClient, content: bytes, content_type: str, reason: str
) -> None:
    serve_feed(content, content_type)
    show_id = await new_show(authed)

    response = await add(authed, show_id)

    assert response.status_code == 422
    detail = response.json()["detail"][0]
    assert detail["loc"] == ["body", "value"] and reason in detail["msg"]
    assert (await authed.get(f"/api/shows/{show_id}/sources")).json() == []


@respx.mock
async def test_unreachable_feeds_are_rejected_with_the_reason(authed: AsyncClient) -> None:
    show_id = await new_show(authed)

    respx.get(FEED).respond(404)
    assert "HTTP 404" in (await add(authed, show_id)).json()["detail"][0]["msg"]
    respx.get(FEED).mock(side_effect=httpx.ReadTimeout("slow"))
    assert "too long" in (await add(authed, show_id)).json()["detail"][0]["msg"]
    respx.get(FEED).mock(side_effect=httpx.ConnectError("refused"))
    assert "Could not connect" in (await add(authed, show_id)).json()["detail"][0]["msg"]


async def test_internal_addresses_are_refused_unless_allowed(
    app: FastAPI, authed: AsyncClient
) -> None:
    show_id = await new_show(authed)

    refused = await add(authed, show_id, value="http://lan.example/feed.xml")
    assert refused.status_code == 422
    assert "private and internal" in refused.json()["detail"][0]["msg"]

    app.dependency_overrides[get_settings] = lambda: make_settings(
        sources_allow_private_networks=True
    )
    with respx.mock:
        respx.get("http://lan.example/feed.xml").respond(200, content=RSS)
        assert (await add(authed, show_id, value="http://lan.example/feed.xml")).status_code == 201


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "rss", "value": "not a url"},
        {"kind": "rss", "value": "ftp://example.com/feed"},
        {"kind": "url", "value": "javascript:alert(1)"},
        {"kind": "rss", "value": "   "},
        {"kind": "web_search", "value": "q" * 501},
        {"kind": "podcast", "value": "https://example.com"},
        {"kind": "rss"},
    ],
)
async def test_values_are_checked_for_their_kind(
    authed: AsyncClient, payload: dict[str, str]
) -> None:
    show_id = await new_show(authed)

    response = await authed.post(f"/api/shows/{show_id}/sources", json=payload)

    assert response.status_code == 422


async def test_a_page_to_watch_is_vetted_but_not_fetched(authed: AsyncClient) -> None:
    show_id = await new_show(authed)

    ok = await authed.post(
        f"/api/shows/{show_id}/sources",
        json={"kind": "url", "value": "https://news.example.com/blog", "name": "Blog"},
    )
    internal = await authed.post(
        f"/api/shows/{show_id}/sources",
        json={"kind": "url", "value": "http://lan.example/admin"},
    )

    assert ok.status_code == 201 and ok.json()["name"] == "Blog"
    assert internal.status_code == 422


async def test_a_search_query_is_free_text(authed: AsyncClient) -> None:
    show_id = await new_show(authed)

    response = await authed.post(
        f"/api/shows/{show_id}/sources",
        json={"kind": "web_search", "value": "  rust language releases this week  "},
    )

    assert response.status_code == 201
    assert response.json()["value"] == "rust language releases this week"
    assert response.json()["name"] is None


@respx.mock
async def test_the_same_source_cannot_be_added_twice(authed: AsyncClient) -> None:
    serve_feed()
    show_id = await new_show(authed)
    await add(authed, show_id)

    again = await add(authed, show_id)

    assert again.status_code == 409
    assert "already added" in again.json()["detail"]


@respx.mock
async def test_two_shows_can_use_the_same_feed(authed: AsyncClient) -> None:
    serve_feed()

    assert (await add(authed, await new_show(authed))).status_code == 201
    assert (await add(authed, await new_show(authed))).status_code == 201


# --- validate -----------------------------------------------------------------------------


@respx.mock
async def test_validate_shows_the_title_and_three_latest_entries(authed: AsyncClient) -> None:
    serve_feed()
    show_id = await new_show(authed)

    response = await authed.post(
        f"/api/shows/{show_id}/sources/validate", json={"kind": "rss", "value": FEED}
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "title": "Example News",
        "entry_count": 4,
        "latest_titles": ["One", "Two", "Three"],
        "detail": None,
    }
    assert (await authed.get(f"/api/shows/{show_id}/sources")).json() == []  # nothing saved


@respx.mock
async def test_validate_reports_a_bad_feed_as_an_answer_not_an_error(
    authed: AsyncClient,
) -> None:
    serve_feed(b"<html/>", "text/html")

    response = await authed.post(
        f"/api/shows/{await new_show(authed)}/sources/validate",
        json={"kind": "rss", "value": FEED},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False and "web page" in response.json()["detail"]


async def test_only_rss_can_be_validated(authed: AsyncClient) -> None:
    response = await authed.post(
        f"/api/shows/{await new_show(authed)}/sources/validate",
        json={"kind": "web_search", "value": "rust"},
    )

    assert response.status_code == 422


# --- read, update, delete -------------------------------------------------------------------


@respx.mock
async def test_list_returns_the_shows_sources(
    authed: AsyncClient,
) -> None:
    serve_feed()
    show_id = await new_show(authed)
    await add(authed, show_id)
    await authed.post(
        f"/api/shows/{show_id}/sources", json={"kind": "web_search", "value": "rust news"}
    )

    listed = (await authed.get(f"/api/shows/{show_id}/sources")).json()

    assert sorted(s["kind"] for s in listed) == ["rss", "web_search"]


@respx.mock
async def test_the_enabled_toggle_persists(authed: AsyncClient) -> None:
    serve_feed()
    show_id = await new_show(authed)
    source = (await add(authed, show_id)).json()
    url = f"/api/shows/{show_id}/sources/{source['id']}"

    off = await authed.patch(url, json={"enabled": False})
    assert off.status_code == 200 and off.json()["enabled"] is False
    assert [s["enabled"] for s in (await authed.get(f"/api/shows/{show_id}/sources")).json()] == [
        False
    ]
    on = await authed.patch(url, json={"enabled": True})
    assert on.json()["enabled"] is True


@respx.mock
async def test_rename_and_clear_the_name(authed: AsyncClient) -> None:
    serve_feed()
    show_id = await new_show(authed)
    source = (await add(authed, show_id)).json()
    url = f"/api/shows/{show_id}/sources/{source['id']}"

    renamed = await authed.patch(url, json={"name": "Renamed"})
    cleared = await authed.patch(url, json={"name": None})

    assert renamed.json()["name"] == "Renamed"
    assert cleared.json()["name"] is None
    assert cleared.json()["enabled"] is True  # untouched


@respx.mock
async def test_changing_a_feed_url_revalidates_and_resets_its_history(
    authed: AsyncClient, db_session: AsyncSession
) -> None:
    serve_feed()
    show_id = await new_show(authed)
    source = (await add(authed, show_id)).json()
    row = await db_session.get(Source, source["id"])
    assert row is not None
    row.last_error = "boom"
    await db_session.flush()
    url = f"/api/shows/{show_id}/sources/{source['id']}"

    respx.get("https://news.example.com/other.xml").respond(200, content=b"<html/>")
    bad = await authed.patch(url, json={"value": "https://news.example.com/other.xml"})
    assert bad.status_code == 422 and bad.json()["detail"][0]["loc"] == ["body", "value"]

    respx.get("https://news.example.com/other.xml").respond(200, content=RSS)
    good = await authed.patch(url, json={"value": "https://news.example.com/other.xml"})

    assert good.status_code == 200
    assert good.json()["value"] == "https://news.example.com/other.xml"
    assert good.json()["last_error"] is None


@respx.mock
async def test_update_rules(authed: AsyncClient) -> None:
    serve_feed()
    show_id = await new_show(authed)
    rss = (await add(authed, show_id)).json()
    query = (
        await authed.post(
            f"/api/shows/{show_id}/sources", json={"kind": "web_search", "value": "rust"}
        )
    ).json()
    base = f"/api/shows/{show_id}/sources"

    assert (await authed.patch(f"{base}/{rss['id']}", json={"value": None})).status_code == 422
    assert (await authed.patch(f"{base}/{rss['id']}", json={"enabled": None})).status_code == 422
    assert (await authed.patch(f"{base}/{rss['id']}", json={"kind": "url"})).status_code == 200
    kinds = {s["id"]: s["kind"] for s in (await authed.get(base)).json()}
    assert kinds[rss["id"]] == "rss"  # the kind is immutable
    # a query is not a URL, but a feed's value must be one
    assert (
        await authed.patch(f"{base}/{rss['id']}", json={"value": "not a url"})
    ).status_code == 422
    assert (
        await authed.patch(f"{base}/{query['id']}", json={"value": "rust 2027"})
    ).status_code == 200
    # moving onto a value that already exists
    clash = await authed.patch(f"{base}/{query['id']}", json={"value": "rust 2027"})
    assert clash.status_code == 200  # unchanged value is not a conflict
    other = (await authed.post(f"{base}", json={"kind": "web_search", "value": "go news"})).json()
    assert (
        await authed.patch(f"{base}/{other['id']}", json={"value": "rust 2027"})
    ).status_code == 409


@respx.mock
async def test_delete_removes_the_source(authed: AsyncClient) -> None:
    serve_feed()
    show_id = await new_show(authed)
    source = (await add(authed, show_id)).json()
    url = f"/api/shows/{show_id}/sources/{source['id']}"

    assert (await authed.delete(url)).status_code == 204
    assert (await authed.get(f"/api/shows/{show_id}/sources")).json() == []
    assert (await authed.delete(url)).status_code == 404


async def test_deleting_a_show_removes_its_sources(
    authed: AsyncClient, db_session: AsyncSession
) -> None:
    show_id = await new_show(authed)
    await authed.post(f"/api/shows/{show_id}/sources", json={"kind": "web_search", "value": "rust"})

    await authed.delete(f"/api/shows/{show_id}")

    assert (await db_session.scalars(Source.__table__.select())).all() == []


# --- ownership and access ---------------------------------------------------------------------


async def test_other_users_sources_are_invisible_and_untouchable(
    authed: AsyncClient, db_session: AsyncSession
) -> None:
    other = await make_user(db_session, "other@example.com")
    theirs = await make_show(db_session, other, slug="theirs")
    source = Source(
        user_id=other.id,
        show_id=theirs.id,
        kind="web_search",
        value="secret topic",
        origin=SourceOrigin.USER,
    )
    db_session.add(source)
    await db_session.flush()
    base = f"/api/shows/{theirs.id}/sources"

    assert (await authed.get(base)).status_code == 404
    assert (await authed.post(base, json={"kind": "web_search", "value": "x"})).status_code == 404
    assert (await authed.patch(f"{base}/{source.id}", json={"enabled": False})).status_code == 404
    assert (await authed.delete(f"{base}/{source.id}")).status_code == 404
    assert (
        await authed.post(f"{base}/validate", json={"kind": "rss", "value": FEED})
    ).status_code == 404
    await db_session.refresh(source)
    assert source.enabled is True


async def test_a_source_id_from_another_show_is_not_found(authed: AsyncClient) -> None:
    mine = await new_show(authed)
    created = await authed.post(
        f"/api/shows/{mine}/sources", json={"kind": "web_search", "value": "rust"}
    )
    elsewhere = await new_show(authed)

    response = await authed.patch(
        f"/api/shows/{elsewhere}/sources/{created.json()['id']}", json={"enabled": False}
    )

    assert response.status_code == 404


async def test_requires_a_session(client: AsyncClient) -> None:
    base = "/api/shows/00000000-0000-4000-8000-000000000000/sources"

    assert (await client.get(base)).status_code == 401
    assert (await client.post(base, json={})).status_code == 401
