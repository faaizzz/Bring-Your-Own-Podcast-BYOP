import json
import uuid
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest
import respx
import structlog
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings
from byop.models import Source, User
from byop.models.enums import CredentialProvider as P
from byop.models.enums import SourceKind
from byop.providers.llm import LLMError
from byop.schemas.discovery import DiscoveredSource
from byop.services.credentials import CredentialResolver
from byop.services.discovery import (
    DiscoveryRequest,
    DiscoveryUnavailable,
    discover_sources,
    pick_model,
    search_model_id,
)
from tests.helpers import make_settings
from tests.models.factories import make_show
from tests.providers.llm.helpers import OPENROUTER_URL, body_of, completion

pytestmark = pytest.mark.usefixtures("fake_dns")


def rss(title: str, items: list[tuple[str, datetime | None]]) -> bytes:
    entries = ""
    for name, when in items:
        date = f"<pubDate>{format_datetime(when)}</pubDate>" if when else ""
        entries += f"<item><title>{name}</title>{date}</item>"
    return (
        f'<?xml version="1.0"?><rss version="2.0"><channel><title>{title}</title>{entries}'
        "</channel></rss>"
    ).encode()


NOW = datetime.now(UTC)
FRESH = rss(
    "Fresh Feed", [("Story A", NOW - timedelta(days=2)), ("Story B", NOW - timedelta(days=9))]
)
STALE = rss("Dead Feed", [("Old", NOW - timedelta(days=400))])
UNDATED = rss("Undated Feed", [("Evergreen", None)])
EMPTY = rss("Empty Feed", [])


def settings(**overrides: object) -> Settings:
    return make_settings(
        openrouter_api_key=SecretStr("sk-or-test-key-123456"),
        default_llm_provider="openrouter",
        default_llm_model="vendor/model",
        **overrides,
    )


def candidates(*items: dict[str, str]) -> str:
    return json.dumps({"candidates": list(items)})


def feed(url: str, name: str = "", reason: str = "Relevant.") -> dict[str, str]:
    return {"kind": "rss", "value": url, "name": name, "reason": reason}


def route_llm(content: str) -> respx.Route:
    return respx.post(OPENROUTER_URL).respond(200, json=completion(content))


def serve(url: str, content: bytes, status: int = 200, ctype: str = "application/rss+xml") -> None:
    respx.get(url).respond(status, content=content, headers={"content-type": ctype})


async def run(
    session: AsyncSession,
    user: User,
    cfg: Settings | None = None,
    *,
    show_id: uuid.UUID | None = None,
    **fields: object,
) -> list[DiscoveredSource]:
    request = DiscoveryRequest(
        user_id=user.id,
        show_id=show_id,
        topic="open-source AI tooling",
        language="en",
        **fields,  # type: ignore[arg-type]
    )
    cfg = cfg or settings()
    return await discover_sources(session, CredentialResolver(session, cfg), cfg, request)


@respx.mock
async def test_keeps_what_checks_out_and_drops_the_rest(
    db_session: AsyncSession, admin_user: User
) -> None:
    route_llm(
        candidates(
            feed("https://a.example/feed.xml", "Alpha", "Covers open models."),
            feed("https://dead.example/feed.xml", "Dead"),
            feed("https://html.example/feed.xml", "NotAFeed"),
            feed("https://empty.example/feed.xml", "Empty"),
            feed("https://undated.example/feed.xml"),
            {
                "kind": "url",
                "value": "https://blog.example/releases",
                "name": "Releases",
                "reason": "x",
            },
            {"kind": "url", "value": "https://gone.example/page", "name": "Gone", "reason": "x"},
            {
                "kind": "web_search",
                "value": "open source ai tooling news",
                "name": "News",
                "reason": "r",
            },
            {"kind": "podcast", "value": "https://ignored.example/", "name": "Unknown kind"},
            feed("https://a.example/feed.xml/", "Duplicate of Alpha"),
            {"kind": "rss", "value": "   ", "name": "Blank"},
        )
    )
    serve("https://a.example/feed.xml", FRESH)
    serve("https://dead.example/feed.xml", STALE)
    serve("https://html.example/feed.xml", b"<html><body>hi</body></html>", ctype="text/html")
    serve("https://empty.example/feed.xml", EMPTY)
    serve("https://undated.example/feed.xml", UNDATED)
    serve("https://blog.example/releases", b"<html>ok</html>", ctype="text/html")
    serve("https://gone.example/page", b"", status=404)

    found = await run(db_session, admin_user)

    assert [(c.kind.value, c.value) for c in found] == [
        ("rss", "https://a.example/feed.xml"),
        ("rss", "https://undated.example/feed.xml"),
        ("url", "https://blog.example/releases"),
        ("web_search", "open source ai tooling news"),
    ]
    alpha = found[0]
    assert alpha.name == "Alpha" and alpha.reason == "Covers open models."
    assert alpha.recent_titles == ["Story A", "Story B"]
    assert found[1].name == "Undated Feed"  # a feed names itself when the model gave no name


@respx.mock
async def test_there_is_always_at_least_one_search_query(
    db_session: AsyncSession, admin_user: User
) -> None:
    route_llm(candidates())

    found = await run(db_session, admin_user)

    searches = [c for c in found if c.kind is SourceKind.WEB_SEARCH]
    assert 1 <= len(searches) <= 3
    assert all("open-source AI tooling" in c.value for c in searches)


@respx.mock
async def test_search_queries_are_capped_at_three(
    db_session: AsyncSession, admin_user: User
) -> None:
    route_llm(
        candidates(
            *({"kind": "web_search", "value": f"query {n}", "name": f"Q{n}"} for n in range(6))
        )
    )

    found = await run(db_session, admin_user)

    assert [c.value for c in found] == ["query 0", "query 1", "query 2"]


@respx.mock
async def test_sources_the_show_already_has_are_not_proposed_again(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    db_session.add_all(
        [
            Source(
                user_id=admin_user.id,
                show_id=show.id,
                kind=SourceKind.RSS,
                value="https://a.example/feed.xml",
            ),
            Source(
                user_id=admin_user.id,
                show_id=show.id,
                kind=SourceKind.WEB_SEARCH,
                value="Query One",
            ),
        ]
    )
    await db_session.flush()
    route_llm(
        candidates(
            feed("https://a.example/feed.xml/", "Alpha again"),
            feed("https://b.example/feed.xml", "Beta"),
            {"kind": "web_search", "value": "query  one", "name": "Q1"},
            {"kind": "web_search", "value": "query two", "name": "Q2"},
        )
    )
    serve("https://b.example/feed.xml", FRESH)

    found = await run(db_session, admin_user, show_id=show.id)

    assert [c.value for c in found] == ["https://b.example/feed.xml", "query two"]


@respx.mock
async def test_internal_addresses_are_never_proposed(
    db_session: AsyncSession, admin_user: User
) -> None:
    route_llm(
        candidates(
            feed("http://internal.example/feed.xml"),
            feed("http://metadata.example/latest"),
            {"kind": "url", "value": "http://internal.example/admin", "name": "Admin"},
        )
    )

    found = await run(db_session, admin_user)

    assert [c.kind for c in found] == [SourceKind.WEB_SEARCH, SourceKind.WEB_SEARCH]


@respx.mock
async def test_the_call_is_attributed_to_the_show_and_asks_the_model_to_search(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    route = route_llm(candidates())

    with structlog.testing.capture_logs() as logs:
        await run(db_session, admin_user, show_id=show.id)

    call = next(entry for entry in logs if entry["event"] == "llm_complete")
    assert call["stage"] == "discovery"
    assert call["show_id"] == str(show.id)
    body = body_of(route)
    assert body["model"] == "vendor/model:online"
    prompt = json.dumps(body["messages"])
    assert "open-source AI tooling" in prompt and "never invent a URL" in prompt


@pytest.mark.parametrize(
    ("provider", "model", "expected"),
    [
        (P.OPENROUTER, "anthropic/claude-sonnet", "anthropic/claude-sonnet:online"),
        (P.OPENROUTER, "anthropic/claude-sonnet:online", "anthropic/claude-sonnet:online"),
        (P.OPENROUTER, "perplexity/sonar", "perplexity/sonar"),
        (P.OPENAI, "gpt-4o-search-preview", "gpt-4o-search-preview"),
        (P.OPENAI_COMPATIBLE, "local-model", "local-model"),
    ],
)
def test_online_variant_only_where_it_applies(provider: P, model: str, expected: str) -> None:
    assert search_model_id(provider, model) == expected


def test_model_choice_prefers_discovery_then_show_then_instance_default() -> None:
    request = DiscoveryRequest(uuid.uuid4(), None, "t", llm_provider="openai", llm_model="gpt-show")
    both = make_settings(
        discovery_llm_provider="openrouter",
        discovery_llm_model="perplexity/sonar",
        default_llm_provider="openai",
        default_llm_model="gpt-default",
    )
    default_only = make_settings(default_llm_provider="openai", default_llm_model="gpt-default")

    assert pick_model(both, request) == (P.OPENROUTER, "perplexity/sonar")
    assert pick_model(default_only, request) == (P.OPENAI, "gpt-show")
    bare = DiscoveryRequest(uuid.uuid4(), None, "t")
    assert pick_model(default_only, bare) == (P.OPENAI, "gpt-default")


def test_no_model_anywhere_is_explained() -> None:
    with pytest.raises(DiscoveryUnavailable, match="DEFAULT_LLM_PROVIDER"):
        pick_model(make_settings(), DiscoveryRequest(uuid.uuid4(), None, "t"))


async def test_an_unconfigured_provider_is_explained(
    db_session: AsyncSession, admin_user: User
) -> None:
    with pytest.raises(DiscoveryUnavailable, match="Settings › Integrations"):
        await run(
            db_session,
            admin_user,
            make_settings(default_llm_provider="openai", default_llm_model="m"),
        )


@respx.mock
async def test_model_failures_propagate(db_session: AsyncSession, admin_user: User) -> None:
    respx.post(OPENROUTER_URL).respond(401, json={"error": {"message": "bad key"}})

    with pytest.raises(LLMError):
        await run(db_session, admin_user)
