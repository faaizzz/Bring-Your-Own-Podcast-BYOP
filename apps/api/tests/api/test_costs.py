from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import get_settings
from byop.models import Show, UsageEvent, User
from byop.models.enums import CostSource, UsageKind
from tests.helpers import make_settings
from tests.models.factories import make_show, make_user


def event(
    user: User,
    show: Show | None,
    *,
    cost: str,
    kind: UsageKind = UsageKind.LLM,
    provider: str = "openrouter",
    stage: str | None = "script",
    when: datetime = datetime(2026, 5, 10, 12, tzinfo=UTC),
    source: CostSource = CostSource.PROVIDER,
    tokens: tuple[int, int] = (100, 50),
    characters: int | None = None,
) -> UsageEvent:
    return UsageEvent(
        user_id=user.id,
        show_id=show.id if show else None,
        kind=kind,
        provider=provider,
        stage=stage,
        cost_usd=Decimal(cost),
        cost_source=source,
        input_tokens=None if kind is UsageKind.TTS else tokens[0],
        output_tokens=None if kind is UsageKind.TTS else tokens[1],
        characters=characters,
        created_at=when,
    )


async def seed(session: AsyncSession, user: User) -> tuple[Show, Show]:
    a = await make_show(session, user, "a")
    b = await make_show(session, user, "b")
    b.title = "Weekly Rust"
    session.add_all(
        [
            event(user, a, cost="0.10"),
            event(user, a, cost="0.05", stage="rank"),
            event(
                user,
                a,
                cost="0.40",
                kind=UsageKind.TTS,
                provider="openai",
                stage="tts",
                characters=2000,
            ),
            event(user, b, cost="1.00", when=datetime(2026, 6, 2, tzinfo=UTC)),
            event(user, b, cost="0", source=CostSource.UNKNOWN, provider="acme"),
            event(user, None, cost="0.20", provider="openai", stage=None),  # its show was deleted
        ]
    )
    await session.flush()
    return a, b


async def summary(authed: AsyncClient, **params: str) -> dict[str, Any]:
    response = await authed.get("/api/costs/summary", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def by_key(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {g["key"]: g for g in body["groups"]}


async def test_grouped_by_show_with_totals_and_a_bucket_for_deleted_shows(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    a, b = await seed(db_session, admin_user)

    body = await summary(authed, group_by="show")

    groups = by_key(body)
    assert Decimal(groups[str(a.id)]["cost_usd"]) == Decimal("0.55")
    assert Decimal(groups[str(a.id)]["llm_cost_usd"]) == Decimal("0.15")
    assert Decimal(groups[str(a.id)]["tts_cost_usd"]) == Decimal("0.40")
    assert groups[str(a.id)]["calls"] == 3 and groups[str(a.id)]["characters"] == 2000
    assert groups[str(b.id)]["label"] == "Weekly Rust" and groups[str(b.id)]["unknown_calls"] == 1
    assert groups[""]["label"] == "Deleted show"
    # Biggest first, and the total is the sum of the groups.
    assert [g["key"] for g in body["groups"]][0] == str(b.id)
    total = body["total"]
    assert Decimal(total["cost_usd"]) == Decimal("1.75") and total["calls"] == 6
    assert sum(Decimal(g["cost_usd"]) for g in body["groups"]) == Decimal(total["cost_usd"])
    assert total["unknown_calls"] == 1 and total["input_tokens"] == 500


async def test_grouped_by_month_oldest_first(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    await seed(db_session, admin_user)

    body = await summary(authed, group_by="month")

    assert [g["key"] for g in body["groups"]] == ["2026-05", "2026-06"]
    assert Decimal(by_key(body)["2026-06"]["cost_usd"]) == Decimal("1.00")


async def test_grouped_by_provider_and_stage(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    await seed(db_session, admin_user)

    providers = by_key(await summary(authed, group_by="provider"))
    assert Decimal(providers["openrouter"]["cost_usd"]) == Decimal("1.15")
    assert Decimal(providers["openai"]["cost_usd"]) == Decimal("0.60")
    assert providers["acme"]["unknown_calls"] == 1

    stages = by_key(await summary(authed, group_by="stage"))
    assert Decimal(stages["script"]["cost_usd"]) == Decimal("1.10")
    assert stages["rank"]["calls"] == 1 and stages["tts"]["characters"] == 2000
    assert stages[""]["label"] == "(none)"


async def test_the_date_range_is_inclusive_on_both_ends(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    await seed(db_session, admin_user)

    june = await summary(authed, group_by="month", **{"from": "2026-06-02", "to": "2026-06-02"})
    assert list(by_key(june)) == ["2026-06"]
    assert june["from"] == "2026-06-02" and june["to"] == "2026-06-02"

    may = await summary(authed, group_by="month", to="2026-05-10")
    assert list(by_key(may)) == ["2026-05"]
    assert (await summary(authed, group_by="month", **{"from": "2026-07-01"}))["groups"] == []


async def test_with_no_usage_everything_is_zero(authed: AsyncClient) -> None:
    body = await summary(authed)

    total = body["total"]
    assert Decimal(total["cost_usd"]) == 0 and total["calls"] == 0
    assert body["groups"] == []


async def test_other_users_usage_is_invisible(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    other = await make_user(db_session, "other@example.com")
    db_session.add(event(other, None, cost="50"))
    await db_session.flush()

    body = await summary(authed, group_by="provider")

    assert body["groups"] == []


async def test_bad_arguments_are_422(authed: AsyncClient) -> None:
    assert (await authed.get("/api/costs/summary", params={"group_by": "color"})).status_code == 422
    backwards = await authed.get(
        "/api/costs/summary", params={"from": "2026-06-02", "to": "2026-06-01"}
    )
    assert backwards.status_code == 422


# --- prices ------------------------------------------------------------------------------------


async def test_prices_list_the_shipped_table(authed: AsyncClient) -> None:
    prices = (await authed.get("/api/pricing")).json()

    gpt = next(p for p in prices if p["kind"] == "llm" and p["name"] == "gpt-4o-mini")
    assert gpt["source"] == "default" and Decimal(gpt["input_per_million"]) == Decimal("0.15")
    kokoro = next(p for p in prices if p["kind"] == "tts" and p["name"] == "kokoro")
    assert Decimal(kokoro["per_million_chars"]) == 0


async def test_an_override_replaces_the_shipped_price_and_can_be_removed(
    authed: AsyncClient,
) -> None:
    put = await authed.put(
        "/api/pricing/overrides",
        json={
            "kind": "llm",
            "name": "gpt-4o-mini",
            "input_per_million": "1.5",
            "output_per_million": "3",
        },
    )
    assert put.status_code == 200 and put.json()["source"] == "override"

    prices = (await authed.get("/api/pricing")).json()
    matching = [p for p in prices if p["kind"] == "llm" and p["name"] == "gpt-4o-mini"]
    assert len(matching) == 1 and matching[0]["source"] == "override"
    assert Decimal(matching[0]["input_per_million"]) == Decimal("1.5")

    again = await authed.put(
        "/api/pricing/overrides",
        json={
            "kind": "llm",
            "name": "gpt-4o-mini",
            "input_per_million": 2,
            "output_per_million": 4,
        },
    )
    assert again.status_code == 200
    prices = (await authed.get("/api/pricing")).json()
    assert len([p for p in prices if p["name"] == "gpt-4o-mini"]) == 1

    deleted = await authed.delete(
        "/api/pricing/overrides", params={"kind": "llm", "name": "gpt-4o-mini"}
    )
    assert deleted.status_code == 204
    prices = (await authed.get("/api/pricing")).json()
    assert next(p for p in prices if p["name"] == "gpt-4o-mini")["source"] == "default"
    missing = await authed.delete(
        "/api/pricing/overrides", params={"kind": "llm", "name": "gpt-4o-mini"}
    )
    assert missing.status_code == 404


async def test_a_new_price_can_be_added_for_an_unlisted_voice(authed: AsyncClient) -> None:
    put = await authed.put(
        "/api/pricing/overrides",
        json={"kind": "tts", "name": "openrouter:fancy", "per_million_chars": "42"},
    )

    assert put.status_code == 200
    assert Decimal(put.json()["per_million_chars"]) == 42
    assert put.json()["input_per_million"] is None


async def test_overrides_need_the_prices_of_their_kind(authed: AsyncClient) -> None:
    for body in (
        {"kind": "llm", "name": "m", "input_per_million": 1},
        {"kind": "llm", "name": "m"},
        {"kind": "tts", "name": "p"},
        {"kind": "tts", "name": "p", "per_million_chars": -1},
        {"kind": "image", "name": "p", "per_million_chars": 1},
        {"kind": "tts", "name": "", "per_million_chars": 1},
    ):
        response = await authed.put("/api/pricing/overrides", json=body)
        assert response.status_code == 422, body


async def test_my_override_changes_what_my_usage_costs(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    from byop.providers.common import UsageRecord
    from byop.services.usage import UsageCollector

    await authed.put(
        "/api/pricing/overrides",
        json={"kind": "tts", "name": "kokoro", "per_million_chars": 10},
    )
    collector = UsageCollector()
    collector.record(
        UsageRecord(
            kind="tts",
            provider="kokoro",
            model=None,
            stage="tts",
            run_id=None,
            show_id=None,
            latency_ms=1,
            characters=1_000_000,
        )
    )
    await collector.flush(db_session, admin_user.id)

    body = await summary(authed, group_by="provider")

    assert Decimal(by_key(body)["kokoro"]["cost_usd"]) == Decimal("10.0")


async def test_pricing_and_costs_need_a_session(client: AsyncClient) -> None:
    assert (await client.get("/api/costs/summary")).status_code == 401
    assert (await client.get("/api/pricing")).status_code == 401


# --- estimate ----------------------------------------------------------------------------------


async def test_the_estimate_adds_the_model_and_the_voices(
    authed: AsyncClient, app: FastAPI
) -> None:
    app.dependency_overrides[get_settings] = lambda: make_settings()
    show = (
        await authed.post(
            "/api/shows",
            json={
                "title": "Estimate me",
                "topic": "AI",
                "target_minutes": 10,
                "items_per_episode": 5,
                "llm_provider": "openai",
                "llm_model": "gpt-4o-mini",
            },
        )
    ).json()
    await authed.put(
        f"/api/shows/{show['id']}/speakers",
        json=[
            {"name": "A", "tts_provider": "openai", "voice_id": "alloy", "voice_params": {}},
            {"name": "B", "tts_provider": "kokoro", "voice_id": "af_heart", "voice_params": {}},
        ],
    )

    body = (await authed.get(f"/api/shows/{show['id']}/estimate")).json()

    assert body["characters"] == 9000 and body["model"] == "gpt-4o-mini"
    # gpt-4o-mini: 0.15 in / 0.60 out per 1M tokens.
    expected_llm = (
        body["input_tokens"] * Decimal("0.15") + body["output_tokens"] * Decimal("0.60")
    ) / 1_000_000
    assert Decimal(body["llm_usd"]) == expected_llm
    # Half of the characters go to openai ($15/1M), half to kokoro (free).
    assert Decimal(body["tts_usd"]) == Decimal(4500) * Decimal(15) / 1_000_000
    assert Decimal(body["total_usd"]) == Decimal(body["llm_usd"]) + Decimal(body["tts_usd"])


async def test_the_estimate_says_what_it_could_not_price(authed: AsyncClient, app: FastAPI) -> None:
    app.dependency_overrides[get_settings] = lambda: make_settings(
        openai_api_key=SecretStr("sk-test-0123456789")
    )
    show = (
        await authed.post(
            "/api/shows",
            json={
                "title": "Unpriced",
                "topic": "AI",
                "llm_provider": "openai",
                "llm_model": "mystery-model",
            },
        )
    ).json()

    body = (await authed.get(f"/api/shows/{show['id']}/estimate")).json()

    assert body["llm_usd"] is None and body["total_usd"] is None
    assert any("mystery-model" in note for note in body["notes"])


async def test_the_estimate_of_an_unknown_show_is_404(authed: AsyncClient) -> None:
    response = await authed.get("/api/shows/00000000-0000-0000-0000-000000000000/estimate")
    assert response.status_code == 404
