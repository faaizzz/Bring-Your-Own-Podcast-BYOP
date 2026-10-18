import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import PriceOverride, User
from byop.models.enums import CostSource, UsageKind
from byop.providers.common import UsageRecord
from byop.services.pricing import default_prices, parse_prices, price_book

BOOK = parse_prices(
    {
        "llm": {
            "gpt-4.1": {"input": 2, "output": 8},
            "gpt-4.1-mini": {"input": 0.4, "output": 1.6},
            "acme/model": {"input": 1, "output": 3},
        },
        "tts": {
            "openai": {"per_million_chars": 15, "models": {"tts-1-hd": 30}},
            "kokoro": {"per_million_chars": 0},
        },
    }
)


def llm(model: str | None, tokens_in: int = 1000, tokens_out: int = 500, cost: str | None = None):  # type: ignore[no-untyped-def]
    return UsageRecord(
        kind="llm",
        provider="openai",
        model=model,
        stage="script",
        run_id=None,
        show_id=None,
        latency_ms=10,
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        cost_usd=Decimal(cost) if cost is not None else None,
    )


def tts(provider: str, model: str | None = None, characters: int = 2000):  # type: ignore[no-untyped-def]
    return UsageRecord(
        kind="tts",
        provider=provider,
        model=model,
        stage="tts",
        run_id=None,
        show_id=None,
        latency_ms=10,
        characters=characters,
    )


def test_the_providers_own_cost_is_preferred_over_the_table() -> None:
    cost, source = BOOK.cost(llm("gpt-4.1", cost="0.123456789"))

    assert (cost, source) == (Decimal("0.123457"), CostSource.PROVIDER)


def test_a_provider_cost_of_zero_is_still_the_providers_word() -> None:
    assert BOOK.cost(llm("gpt-4.1", cost="0")) == (Decimal("0.000000"), CostSource.PROVIDER)


def test_the_table_prices_tokens_per_million() -> None:
    cost, source = BOOK.cost(llm("gpt-4.1", tokens_in=1_000_000, tokens_out=500_000))

    assert (cost, source) == (Decimal("6.000000"), CostSource.PRICE_TABLE)  # 2 + 0.5 * 8


def test_cost_is_unknown_when_neither_provider_nor_table_has_it() -> None:
    assert BOOK.cost(llm("some/unlisted-model")) == (Decimal(0), CostSource.UNKNOWN)
    assert BOOK.cost(llm(None)) == (Decimal(0), CostSource.UNKNOWN)
    assert BOOK.cost(tts("elevenlabs")) == (Decimal(0), CostSource.UNKNOWN)


@pytest.mark.parametrize(
    ("model", "expected_input"),
    [
        ("gpt-4.1", "2"),
        ("gpt-4.1-2025-04-14", "2"),  # a dated snapshot of gpt-4.1
        ("gpt-4.1-mini", "0.4"),  # the longest match wins
        ("gpt-4.1-mini-2025-04-14", "0.4"),
        ("acme/model:free", "1"),
        ("acme/model-pro", "1"),
    ],
)
def test_models_match_by_longest_prefix(model: str, expected_input: str) -> None:
    price = BOOK.llm_price(model)

    assert price is not None and price.input_per_million == Decimal(expected_input)


def test_a_longer_name_is_not_mistaken_for_a_prefix_match() -> None:
    assert BOOK.llm_price("gpt-4.10") is None  # "gpt-4.1" followed by "0" is another model
    assert BOOK.llm_price("gpt-4") is None


def test_tts_is_priced_per_million_characters_with_model_prices_first() -> None:
    assert BOOK.cost(tts("openai", characters=1_000_000)) == (
        Decimal("15.000000"),
        CostSource.PRICE_TABLE,
    )
    assert BOOK.cost(tts("openai", "tts-1-hd", characters=1_000_000))[0] == Decimal("30.000000")
    assert BOOK.cost(tts("openai", "unknown-model", characters=1_000_000))[0] == Decimal(
        "15.000000"
    )


def test_a_free_local_voice_costs_nothing_but_is_not_unknown() -> None:
    assert BOOK.cost(tts("kokoro")) == (Decimal("0.000000"), CostSource.PRICE_TABLE)


def test_the_shipped_table_loads_and_prices_the_common_models() -> None:
    book = default_prices()

    assert book.llm_price("gpt-4o-mini") is not None
    assert book.tts_price("openai", "tts-1") == Decimal("15.0")
    assert book.tts_price("kokoro", None) == Decimal("0.0")
    for price in book.llm.values():
        assert price.input_per_million >= 0 and price.output_per_million >= 0


async def test_user_overrides_win_over_the_shipped_table(
    db_session: AsyncSession, admin_user: User
) -> None:
    db_session.add_all(
        [
            PriceOverride(
                user_id=admin_user.id,
                kind=UsageKind.LLM,
                name="gpt-4o-mini",
                input_per_million=Decimal(1),
                output_per_million=Decimal(2),
            ),
            PriceOverride(
                user_id=admin_user.id,
                kind=UsageKind.TTS,
                name="elevenlabs",
                per_million_chars=Decimal(100),
            ),
        ]
    )
    await db_session.flush()

    book = await price_book(db_session, admin_user.id)

    assert book.cost(llm("gpt-4o-mini", 1_000_000, 1_000_000))[0] == Decimal("3.000000")
    assert book.cost(tts("elevenlabs", characters=1_000_000))[0] == Decimal("100.000000")
    # ...and a price the shipped table lacks can be filled in.
    other = await price_book(db_session, uuid.uuid4())
    assert other.cost(tts("elevenlabs"))[1] is not CostSource.UNKNOWN  # shipped default exists
