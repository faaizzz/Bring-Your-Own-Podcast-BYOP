import asyncio
import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
import respx
import structlog
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings
from byop.models import Item, Run, Source, User
from byop.models.enums import RunTrigger, SourceKind
from byop.services.credentials import CredentialResolver
from byop.services.ingest.pipeline import IngestResult, ShowMissing, ingest_show
from byop.services.user_settings import save_discovery_choice
from tests.helpers import make_settings
from tests.models.factories import make_show, make_user
from tests.providers.llm.helpers import OPENROUTER_URL, body_of, completion

pytestmark = pytest.mark.usefixtures("fake_dns")

NOW = datetime.now(UTC)
EN_BODY = "Researchers explained the findings in detail and the community reacted with interest."
DE_BODY = (
    "Die Forscher erklärten die Ergebnisse ausführlich und die Gemeinschaft reagierte interessiert."
)


def rss_date(days_ago: float) -> str:
    return format_datetime(NOW - timedelta(days=days_ago))


def feed(*entries: tuple[str, str, float | str | None], body: str = EN_BODY) -> bytes:
    """An RSS feed; each entry is (title, link, age in days | raw date text | None)."""
    items = ""
    for title, link, when in entries:
        if isinstance(when, int | float):
            date = f"<pubDate>{rss_date(when)}</pubDate>"
        elif when:
            date = f"<pubDate>{when}</pubDate>"
        else:
            date = ""
        items += (
            f"<item><title>{title}</title><link>{link}</link>"
            f"<description>{body}</description>{date}</item>"
        )
    head = '<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
    return f"{head}{items}</channel></rss>".encode()


def serve(
    url: str, content: bytes, status: int = 200, ctype: str = "application/rss+xml"
) -> respx.Route:
    return respx.get(url).respond(status, content=content, headers={"content-type": ctype})


async def add_source(
    session: AsyncSession,
    user: User,
    show_id: object,
    kind: SourceKind,
    value: str,
    **fields: object,
) -> Source:
    source = Source(user_id=user.id, show_id=show_id, kind=kind, value=value, **fields)
    session.add(source)
    await session.flush()
    return source


async def run(
    session: AsyncSession, show_id: object, cfg: Settings | None = None, **kwargs: object
) -> IngestResult:
    cfg = cfg or make_settings()
    return await ingest_show(session, CredentialResolver(session, cfg), cfg, show_id, **kwargs)  # type: ignore[arg-type]


async def items_of(session: AsyncSession, show_id: object) -> list[Item]:
    rows = await session.scalars(select(Item).where(Item.show_id == show_id).order_by(Item.title))
    return list(rows)


@respx.mock
async def test_collects_new_items_from_a_feed(db_session: AsyncSession, admin_user: User) -> None:
    show = await make_show(db_session, admin_user)
    source = await add_source(
        db_session, admin_user, show.id, SourceKind.RSS, "https://a.example.com/feed"
    )
    serve(
        "https://a.example.com/feed",
        feed(
            ("Chip makers announce a new generation of processors", "https://a.example.com/1", 0.5),
            ("Farmers adopt autonomous tractors across the region", "https://a.example.com/2", 1.0),
        ),
    )

    result = await run(db_session, show.id)

    assert (result.new_items, result.fetched, result.duplicates) == (2, 2, 0)
    items = await items_of(db_session, show.id)
    assert [i.title for i in items] == [
        "Chip makers announce a new generation of processors",
        "Farmers adopt autonomous tractors across the region",
    ]
    assert all(i.source_id == source.id and i.user_id == admin_user.id for i in items)
    assert all(i.language == "en" and i.published_at is not None for i in items)
    await db_session.refresh(source)
    assert source.last_error is None and source.last_fetched_at is not None


@respx.mock
async def test_running_ingest_again_changes_nothing(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    await add_source(db_session, admin_user, show.id, SourceKind.RSS, "https://a.example.com/feed")
    serve(
        "https://a.example.com/feed",
        feed(
            (
                "Chip makers announce a new generation of processors",
                "https://a.example.com/1?utm_source=x",
                0.5,
            ),
            (
                "Farmers adopt autonomous tractors across the region",
                "https://www.a.example.com/2/",
                1.0,
            ),
        ),
    )

    first = await run(db_session, show.id)
    before = [(i.id, i.canonical_url, i.ingested_at) for i in await items_of(db_session, show.id)]
    second = await run(db_session, show.id)
    third = await run(db_session, show.id)

    assert (first.new_items, second.new_items, third.new_items) == (2, 0, 0)
    assert second.duplicates == 2
    assert [
        (i.id, i.canonical_url, i.ingested_at) for i in await items_of(db_session, show.id)
    ] == before


@respx.mock
async def test_a_failing_source_is_recorded_and_the_others_still_run(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    good = await add_source(
        db_session, admin_user, show.id, SourceKind.RSS, "https://good.example.com/feed"
    )
    broken = await add_source(
        db_session, admin_user, show.id, SourceKind.RSS, "https://broken.example.com/feed"
    )
    html = await add_source(
        db_session, admin_user, show.id, SourceKind.RSS, "https://html.example.com/feed"
    )
    slow = await add_source(
        db_session, admin_user, show.id, SourceKind.RSS, "https://slow.example.com/feed"
    )
    serve(
        "https://good.example.com/feed",
        feed(("Solar capacity doubles in two years worldwide", "https://good.example.com/1", 0.2)),
    )
    respx.get("https://broken.example.com/feed").respond(500)
    serve("https://html.example.com/feed", b"<html>nope</html>", ctype="text/html")
    respx.get("https://slow.example.com/feed").mock(side_effect=httpx.ReadTimeout("slow"))

    result = await run(db_session, show.id)

    assert result.new_items == 1
    reports = {r.source_id: r for r in result.sources}
    assert reports[good.id].error is None and reports[good.id].fetched == 1
    assert "HTTP 500" in (reports[broken.id].error or "")
    for source in (good, broken, html, slow):
        await db_session.refresh(source)
    assert good.last_error is None and good.last_fetched_at is not None
    assert "HTTP 500" in (broken.last_error or "") and broken.last_fetched_at is None
    assert "web page" in (html.last_error or "")
    assert "too long" in (slow.last_error or "")


@respx.mock
async def test_a_source_that_recovers_clears_its_error(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    source = await add_source(
        db_session,
        admin_user,
        show.id,
        SourceKind.RSS,
        "https://a.example.com/feed",
        last_error="HTTP 500",
    )
    serve(
        "https://a.example.com/feed",
        feed(("Fresh story about orbital launches this week", "https://a.example.com/1", 0.1)),
    )

    await run(db_session, show.id)

    await db_session.refresh(source)
    assert source.last_error is None


@respx.mock
async def test_a_source_that_takes_too_long_is_cut_off(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    source = await add_source(
        db_session, admin_user, show.id, SourceKind.RSS, "https://slow.example.com/feed"
    )

    async def stall(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(2)
        return httpx.Response(200)

    respx.get("https://slow.example.com/feed").mock(side_effect=stall)

    result = await run(db_session, show.id, make_settings(ingest_source_timeout_s=0.1))

    assert result.new_items == 0
    await db_session.refresh(source)
    assert source.last_error == "The source took too long to answer"


@respx.mock
async def test_disabled_sources_are_not_fetched(db_session: AsyncSession, admin_user: User) -> None:
    show = await make_show(db_session, admin_user)
    await add_source(
        db_session,
        admin_user,
        show.id,
        SourceKind.RSS,
        "https://off.example.com/feed",
        enabled=False,
    )
    route = serve(
        "https://off.example.com/feed",
        feed(("Never fetched story about nothing", "https://off.example.com/1", 0.1)),
    )

    result = await run(db_session, show.id)

    assert route.call_count == 0 and result.sources == [] and result.new_items == 0


@respx.mock
async def test_only_fresh_items_are_collected_and_dates_in_both_formats_work(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    await add_source(
        db_session, admin_user, show.id, SourceKind.RSS, "https://rss.example.com/feed"
    )

    def atom_entry(title: str, link: str, updated: str) -> str:
        return (
            f"<entry><title>{title}</title><id>{link}</id><link href='{link}'/>"
            f"<updated>{updated}</updated><summary>{EN_BODY}</summary></entry>"
        )

    recent = (NOW - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    month_old = (NOW - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    atom = (
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>A</title>'
        + atom_entry(
            "Marine biologists tag migrating humpback whales",
            "https://atom.example.com/new",
            recent,
        )
        + atom_entry(
            "Museum reopens after a long renovation", "https://atom.example.com/old", month_old
        )
        + "</feed>"
    ).encode()
    await add_source(
        db_session, admin_user, show.id, SourceKind.RSS, "https://atom.example.com/feed"
    )
    serve(
        "https://rss.example.com/feed",
        feed(
            (
                "Volcano observatory records unusual seismic swarm",
                "https://rss.example.com/new",
                0.2,
            ),
            ("Council debates the new cycling lane proposal", "https://rss.example.com/old", 7),
            (
                "Local library launches a tool-lending programme",
                "https://rss.example.com/undated",
                None,
            ),
        ),
    )
    serve("https://atom.example.com/feed", atom, ctype="application/atom+xml")

    result = await run(db_session, show.id)

    assert result.fetched == 5 and result.stale == 2 and result.new_items == 3
    assert {i.title for i in await items_of(db_session, show.id)} == {
        "Volcano observatory records unusual seismic swarm",
        "Local library launches a tool-lending programme",
        "Marine biologists tag migrating humpback whales",
    }  # RFC 822 and ISO 8601 dates both parsed; the undated item is kept


@respx.mock
async def test_the_freshness_window_is_configurable(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    await add_source(db_session, admin_user, show.id, SourceKind.RSS, "https://a.example.com/feed")
    serve(
        "https://a.example.com/feed",
        feed(("Story from five days ago about glaciers", "https://a.example.com/1", 5)),
    )

    narrow = await run(db_session, show.id)
    wide = await run(db_session, show.id, make_settings(ingest_freshness_days=7))

    assert (narrow.new_items, narrow.stale) == (0, 1)
    assert wide.new_items == 1


@respx.mock
async def test_items_in_another_language_are_filtered_out(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)  # an English show
    await add_source(db_session, admin_user, show.id, SourceKind.RSS, "https://en.example.com/feed")
    await add_source(db_session, admin_user, show.id, SourceKind.RSS, "https://de.example.com/feed")
    serve(
        "https://en.example.com/feed",
        feed(
            ("Engineers test a new bridge design in the harbour", "https://en.example.com/1", 0.1)
        ),
    )
    serve(
        "https://de.example.com/feed",
        feed(
            (
                "Ingenieure testen einen neuen Brückenentwurf im Hafen",
                "https://de.example.com/1",
                0.1,
            ),
            body=DE_BODY,
        ),
    )

    result = await run(db_session, show.id)

    assert (result.new_items, result.wrong_language) == (1, 1)
    assert [i.language for i in await items_of(db_session, show.id)] == ["en"]


@respx.mock
async def test_a_german_show_keeps_german_items(db_session: AsyncSession, admin_user: User) -> None:
    show = await make_show(db_session, admin_user)
    show.language = "de-AT"
    await db_session.flush()
    await add_source(db_session, admin_user, show.id, SourceKind.RSS, "https://de.example.com/feed")
    serve(
        "https://de.example.com/feed",
        feed(
            (
                "Ingenieure testen einen neuen Brückenentwurf im Hafen",
                "https://de.example.com/1",
                0.1,
            ),
            body=DE_BODY,
        ),
    )

    result = await run(db_session, show.id)

    assert result.new_items == 1 and result.wrong_language == 0


@respx.mock
async def test_the_same_story_from_two_feeds_is_collected_once(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    await add_source(db_session, admin_user, show.id, SourceKind.RSS, "https://a.example.com/feed")
    await add_source(db_session, admin_user, show.id, SourceKind.RSS, "https://b.example.com/feed")
    serve(
        "https://a.example.com/feed",
        feed(("OpenAI releases new GPT model for developers", "https://a.example.com/gpt", 0.3)),
    )
    serve(
        "https://b.example.com/feed",
        feed(
            (
                "OpenAI releases a new GPT model for developers",
                "https://b.example.org/story/42",
                0.2,
            )
        ),
    )

    result = await run(db_session, show.id)

    assert (result.new_items, result.duplicates) == (1, 1)


@respx.mock
async def test_a_watched_page_becomes_one_item_that_updates_when_it_changes(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    await add_source(
        db_session, admin_user, show.id, SourceKind.URL, "https://blog.example.com/releases"
    )
    paragraph = (
        "The maintainers shipped a new release this week with a rewritten scheduler, better error "
        "messages and support for running on small devices, after many months of testing. "
    )

    def page(extra: str) -> bytes:
        return (
            f"<html><head><title>Releases</title></head><body><nav><a href='/'>Home</a></nav>"
            f"<article><h1>Releases</h1><p>{paragraph * 3}</p><p>{extra}{paragraph}</p></article>"
            "<footer>Terms</footer></body></html>"
        ).encode()

    route = serve(
        "https://blog.example.com/releases", page("Version 1."), ctype="text/html; charset=utf-8"
    )
    first = await run(db_session, show.id)
    same = await run(db_session, show.id)
    route.respond(200, content=page("Version 2 is out now."), headers={"content-type": "text/html"})
    changed = await run(db_session, show.id)

    assert (first.new_items, same.new_items, same.updated_items) == (1, 0, 0)
    assert (changed.new_items, changed.updated_items) == (0, 1)
    items = await items_of(db_session, show.id)
    assert len(items) == 1 and items[0].canonical_url == "https://blog.example.com/releases"
    assert "Version 2" in items[0].summary


@respx.mock
async def test_a_page_without_text_is_a_source_error(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    source = await add_source(
        db_session, admin_user, show.id, SourceKind.URL, "https://blank.example.com/"
    )
    serve("https://blank.example.com/", b"<html><body></body></html>", ctype="text/html")

    result = await run(db_session, show.id)

    assert result.new_items == 0
    await db_session.refresh(source)
    assert source.last_error == "No readable text was found on the page"


def search_settings() -> Settings:
    return make_settings(
        openrouter_api_key=SecretStr("sk-or-test-key-123456"),
        default_llm_provider="openrouter",
        default_llm_model="vendor/model",
    )


@respx.mock
async def test_web_search_sources_use_the_model_and_the_same_filters(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    await add_source(db_session, admin_user, show.id, SourceKind.WEB_SEARCH, "rust language news")
    answer = {
        "items": [
            {
                "title": "Rust team announces the next edition of the language",
                "url": "https://blog.rust-lang.org/news?utm_source=x",
                "summary": f"<p>{EN_BODY}</p>",
                "published_at": (NOW - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            {
                "title": "An old announcement from last year about Rust",
                "url": "https://old.example.com/rust",
                "summary": EN_BODY,
                "published_at": "2025-01-01",
            },
            {"title": "Entry with a broken link", "url": "not a url", "summary": EN_BODY},
            {"title": "", "url": "https://example.com/no-title"},
        ]
    }
    route = respx.post(OPENROUTER_URL).respond(200, json=completion(json.dumps(answer)))
    run_row = Run(user_id=admin_user.id, show_id=show.id, trigger=RunTrigger.MANUAL)
    db_session.add(run_row)
    await db_session.flush()

    with structlog.testing.capture_logs() as logs:
        result = await run(db_session, show.id, search_settings(), run_id=run_row.id)

    assert (result.new_items, result.stale, result.invalid) == (1, 1, 1)
    [item] = await items_of(db_session, show.id)
    assert item.canonical_url == "https://blog.rust-lang.org/news"
    assert item.summary == EN_BODY  # markup removed
    call = next(e for e in logs if e["event"] == "llm_complete")
    assert (call["stage"], call["show_id"], call["run_id"]) == (
        "ingest",
        str(show.id),
        str(run_row.id),
    )
    body = body_of(route)
    assert body["model"] == "vendor/model:online"
    assert "rust language news" in json.dumps(body["messages"])


@respx.mock
async def test_web_search_sources_use_the_model_saved_in_settings(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    await add_source(db_session, admin_user, show.id, SourceKind.WEB_SEARCH, "rust language news")
    await save_discovery_choice(db_session, admin_user.id, "openrouter", "perplexity/sonar")
    route = respx.post(OPENROUTER_URL).respond(200, json=completion(json.dumps({"items": []})))

    await run(db_session, show.id, search_settings())

    assert body_of(route)["model"] == "perplexity/sonar"  # not the default, not ':online'


@respx.mock
async def test_web_search_without_a_model_is_a_source_error_not_a_crash(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    source = await add_source(db_session, admin_user, show.id, SourceKind.WEB_SEARCH, "anything")
    serve(
        "https://a.example.com/feed",
        feed(("Unrelated feed story about satellites", "https://a.example.com/1", 0.1)),
    )
    await add_source(db_session, admin_user, show.id, SourceKind.RSS, "https://a.example.com/feed")

    result = await run(db_session, show.id)  # no model configured

    assert result.new_items == 1
    await db_session.refresh(source)
    assert source.last_error == "No language model is set up for web search sources"


@respx.mock
async def test_a_failing_model_only_fails_its_source(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    source = await add_source(db_session, admin_user, show.id, SourceKind.WEB_SEARCH, "anything")
    respx.post(OPENROUTER_URL).respond(401, json={"error": {"message": "bad key"}})

    result = await run(db_session, show.id, search_settings())

    assert result.new_items == 0
    await db_session.refresh(source)
    assert source.last_error is not None and "language model failed" in source.last_error


@respx.mock
async def test_a_run_gets_stage_and_progress_updates(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    run_row = Run(user_id=admin_user.id, show_id=show.id, trigger=RunTrigger.MANUAL)
    db_session.add(run_row)
    await db_session.flush()

    await run(db_session, show.id, run_id=run_row.id)

    await db_session.refresh(run_row)
    assert (run_row.stage, run_row.progress) == ("ingest", 20)


async def test_a_missing_show_is_reported(db_session: AsyncSession) -> None:
    import uuid

    with pytest.raises(ShowMissing):
        await run(db_session, uuid.uuid4())


@respx.mock
async def test_one_users_items_never_mix_with_anothers(
    db_session: AsyncSession, admin_user: User
) -> None:
    other = await make_user(db_session, "other@example.com")
    mine = await make_show(db_session, admin_user)
    theirs = await make_show(db_session, other, slug="theirs")
    for show, user in ((mine, admin_user), (theirs, other)):
        await add_source(
            db_session, user, show.id, SourceKind.RSS, "https://shared.example.com/feed"
        )
    serve(
        "https://shared.example.com/feed",
        feed(("A story that both shows would like to cover", "https://shared.example.com/1", 0.1)),
    )

    a = await run(db_session, mine.id)
    b = await run(db_session, theirs.id)

    assert (a.new_items, b.new_items) == (1, 1)
    assert {i.user_id for i in await items_of(db_session, mine.id)} == {admin_user.id}


def test_the_result_serialises_for_the_task_and_the_cli() -> None:
    assert IngestResult(new_items=2).as_dict()["new_items"] == 2
