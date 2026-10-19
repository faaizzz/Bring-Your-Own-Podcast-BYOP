import json

import pytest
import respx
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import User
from byop.redis_client import get_redis_client
from byop.services.credentials import CredentialResolver
from byop.services.provider_ref import ProviderRef
from byop.services.web_search import WebSearch, check_web_search
from tests.helpers import make_settings
from tests.models.factories import make_connection

MODELS = "https://openrouter.ai/api/v1/models"
CATALOG = {
    "data": [
        {"id": "vendor/chat", "name": "Chat", "architecture": {"output_modalities": ["text"]}},
        {"id": "vendor/paint", "name": "Paint", "architecture": {"output_modalities": ["image"]}},
    ]
}


@pytest.fixture(autouse=True)
async def clean_cache() -> None:
    redis = get_redis_client()
    for key in await redis.keys("models:*"):
        await redis.delete(key)


def resolver(session: AsyncSession) -> CredentialResolver:
    return CredentialResolver(
        session,
        make_settings(
            openrouter_api_key=SecretStr("sk-or-test-key-123456"),
            openai_api_key=SecretStr("sk-openai-test-key-123456"),
        ),
    )


async def check(session: AsyncSession, user: User, ref: str, model: str):  # type: ignore[no-untyped-def]
    return await check_web_search(
        resolver(session), get_redis_client(), user.id, ProviderRef.parse(ref), model
    )


@respx.mock
@pytest.mark.parametrize("model", ["perplexity/sonar", "vendor/chat:online"])
async def test_openrouter_search_models_need_no_lookup(
    db_session: AsyncSession, admin_user: User, model: str
) -> None:
    route = respx.get(MODELS).respond(200, json=CATALOG)

    result = await check(db_session, admin_user, "openrouter", model)

    assert result.support is WebSearch.YES and not route.called


@respx.mock
async def test_any_openrouter_text_model_can_search_through_the_online_plugin(
    db_session: AsyncSession, admin_user: User
) -> None:
    respx.get(MODELS).respond(200, json=CATALOG)

    result = await check(db_session, admin_user, "openrouter", "vendor/chat")

    assert result.support is WebSearch.YES and result.provider_label == "OpenRouter"


@respx.mock
async def test_an_openrouter_model_that_makes_no_text_or_does_not_exist_cannot(
    db_session: AsyncSession, admin_user: User
) -> None:
    respx.get(MODELS).respond(200, json=CATALOG)

    paint = await check(db_session, admin_user, "openrouter", "vendor/paint")
    ghost = await check(db_session, admin_user, "openrouter", "vendor/ghost")

    assert paint.support is WebSearch.NO and "does not produce text" in (paint.message or "")
    assert ghost.support is WebSearch.NO and "does not offer a model" in (ghost.message or "")
    for result in (paint, ghost):
        assert "DISCOVERY_LLM_PROVIDER" in (result.message or "")  # says how to fix it


@respx.mock
async def test_when_the_model_list_is_unavailable_the_answer_is_unknown(
    db_session: AsyncSession, admin_user: User
) -> None:
    respx.get(MODELS).respond(503)

    result = await check(db_session, admin_user, "openrouter", "vendor/chat")

    assert result.support is WebSearch.UNKNOWN
    assert "Could not check" in (result.message or "")


@respx.mock
async def test_the_capabilities_survive_the_model_list_cache(
    db_session: AsyncSession, admin_user: User
) -> None:
    route = respx.get(MODELS).respond(200, json=CATALOG)

    await check(db_session, admin_user, "openrouter", "vendor/paint")
    again = await check(db_session, admin_user, "openrouter", "vendor/paint")

    assert route.call_count == 1  # the second answer came from Redis
    assert again.support is WebSearch.NO


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-4o-search-preview", WebSearch.YES),
        ("gpt-4o-mini-search-preview", WebSearch.YES),
        ("gpt-4o", WebSearch.NO),
    ],
)
async def test_openai_only_searches_with_its_search_models(
    db_session: AsyncSession, admin_user: User, model: str, expected: WebSearch
) -> None:
    result = await check(db_session, admin_user, "openai", model)

    assert result.support is expected
    if expected is WebSearch.NO:
        assert "search-preview" in (result.message or "")


async def test_a_connection_is_as_good_as_its_web_search_flag(
    db_session: AsyncSession, admin_user: User
) -> None:
    searching = await make_connection(db_session, admin_user, "Sonar box", web_search=True)
    plain = await make_connection(db_session, admin_user, "Plain box")

    yes = await check(db_session, admin_user, f"conn:{searching.id}", "any")
    no = await check(db_session, admin_user, f"conn:{plain.id}", "llama3")

    assert yes.support is WebSearch.YES and yes.provider_label == "Sonar box"
    assert no.support is WebSearch.NO
    assert "Plain box" in (no.message or "") and "Web search" in (no.message or "")


async def test_a_provider_that_is_not_set_up_is_unknown_not_incapable(
    db_session: AsyncSession, admin_user: User
) -> None:
    unconfigured = CredentialResolver(db_session, make_settings())

    result = await check_web_search(
        unconfigured,
        get_redis_client(),
        admin_user.id,
        ProviderRef.parse("openrouter"),
        "vendor/chat",
    )

    assert result.support is WebSearch.UNKNOWN and result.message is None


async def test_the_cache_payload_is_plain_json() -> None:
    # Documented shape: a regression here would silently drop capabilities from cached lists.
    from byop.providers.llm import ModelInfo
    from byop.services.models import _decode, _encode

    info = ModelInfo(
        "a", "A", supported_parameters=("tools",), output_modalities=("text",), web_search=True
    )

    assert json.loads(_encode([info]))[0]["web_search"] is True
    assert _decode(_encode([info])) == [info]
    legacy = json.dumps(
        [{"id": "a", "name": "A", "context_length": None, "prompt": None, "completion": None}]
    )
    assert _decode(legacy)[0].web_search is None
