import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
import structlog
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from byop.config import Settings
from byop.models import Episode, Item, Run, Show, User
from byop.models.enums import RunStatus, RunTrigger
from byop.services import ranking
from byop.services.credentials import CredentialResolver
from byop.services.ranking import (
    CANDIDATE_LIMIT,
    RankedItem,
    RankedSelection,
    available_items,
    commit_items,
    rank_items,
    release_items,
    reserve_items,
    select_for_run,
)
from tests.helpers import make_settings
from tests.models.factories import make_show, make_user
from tests.providers.llm.helpers import OPENROUTER_URL, body_of, completion

NOW = datetime.now(UTC)


def configured() -> Settings:
    return make_settings(
        openrouter_api_key=SecretStr("sk-or-test-key-123456"),
        default_llm_provider="openrouter",
        default_llm_model="vendor/model",
    )


async def add_items(
    session: AsyncSession, show: Show, count: int, *, prefix: str = "Story"
) -> list[Item]:
    """Items numbered 1..count, item 1 the newest."""
    items = [
        Item(
            user_id=show.user_id,
            show_id=show.id,
            canonical_url=f"https://news.example.com/{prefix.lower()}-{n}",
            content_hash=f"{prefix}{n}".ljust(64, "0"),
            title=f"{prefix} {n}",
            summary=f"What happened in {prefix} {n}.",
            published_at=NOW - timedelta(hours=n),
            ingested_at=NOW - timedelta(hours=n),
        )
        for n in range(1, count + 1)
    ]
    session.add_all(items)
    await session.flush()
    return items


async def add_run(session: AsyncSession, show: Show, status: RunStatus = RunStatus.QUEUED) -> Run:
    """A show may have only one queued or running run, so a competitor for the same stories
    is a run waiting for review (it still holds what it picked)."""
    run = Run(user_id=show.user_id, show_id=show.id, trigger=RunTrigger.MANUAL, status=status)
    session.add(run)
    await session.flush()
    return run


def answer(*picks: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json=completion(json.dumps({"selections": list(picks)})))


def pick(
    item: int, score: float = 8, reason: str = "Matters.", supporting: list[int] | None = None
) -> dict[str, object]:
    return {"item": item, "score": score, "reason": reason, "supporting": supporting or []}


async def rank(
    session: AsyncSession, show: Show, items: list[Item], **kwargs: object
) -> RankedSelection:
    cfg = configured()
    return await rank_items(CredentialResolver(session, cfg), cfg, show, items, **kwargs)  # type: ignore[arg-type]


# --- selection and merging -----------------------------------------------------------------


@respx.mock
async def test_the_models_picks_become_the_selection_best_first(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    show.items_per_episode = 3
    items = await add_items(db_session, show, 8)
    respx.post(OPENROUTER_URL).mock(
        return_value=answer(
            pick(5, 6.5, "Solid."), pick(2, 9.2, "The big one."), pick(7, 7.0, "Fresh angle.")
        )
    )

    selection = await rank(db_session, show, items)

    assert [p.item_id for p in selection.items] == [items[1].id, items[6].id, items[4].id]
    assert [p.score for p in selection.items] == [9.2, 7.0, 6.5]
    assert selection.items[0].reason == "The big one."
    assert (
        not selection.used_fallback and selection.candidates == 8 and selection.merged_groups == []
    )


@respx.mock
async def test_coverage_of_the_same_event_is_merged_into_the_best_item(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    items = await add_items(db_session, show, 6)
    respx.post(OPENROUTER_URL).mock(
        return_value=answer(pick(4, 9, "Best coverage.", supporting=[1, 6]), pick(2, 7))
    )

    selection = await rank(db_session, show, items)

    main = selection.items[0]
    assert main.item_id == items[3].id
    assert set(main.supporting_item_ids) == {items[0].id, items[5].id}
    assert selection.merged_groups == [[items[3].id, items[0].id, items[5].id]]
    assert set(selection.reserved_ids) == {items[3].id, items[0].id, items[5].id, items[1].id}


@respx.mock
async def test_the_prompt_carries_topic_style_hints_limit_and_numbered_items(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    show.topic = "open-source AI tooling"
    show.ranking_hints = "Prefer releases over funding news"
    show.items_per_episode = 4
    items = await add_items(db_session, show, 3)
    route = respx.post(OPENROUTER_URL).mock(return_value=answer(pick(1)))

    with structlog.testing.capture_logs() as logs:
        await rank(db_session, show, items, run_id=uuid.UUID(int=7))

    prompt = json.dumps(body_of(route)["messages"])
    assert "open-source AI tooling" in prompt and "Prefer releases over funding news" in prompt
    assert "Choose the 4 best stories" in prompt and "tight briefing" in prompt
    assert "[1] (" in prompt and "Story 1" in prompt and "[3] (" in prompt
    call = next(e for e in logs if e["event"] == "llm_complete")
    assert (call["stage"], call["show_id"], call["run_id"]) == (
        "ranking",
        str(show.id),
        str(uuid.UUID(int=7)),
    )


@respx.mock
async def test_without_hints_the_prompt_has_no_priorities_section(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    items = await add_items(db_session, show, 2)
    route = respx.post(OPENROUTER_URL).mock(return_value=answer(pick(1)))

    await rank(db_session, show, items)

    assert "priorities" not in json.dumps(body_of(route)["messages"])


@respx.mock
async def test_only_the_newest_candidates_are_shown_to_the_model(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    items = await add_items(db_session, show, CANDIDATE_LIMIT + 15)
    route = respx.post(OPENROUTER_URL).mock(return_value=answer(pick(1)))

    selection = await rank(db_session, show, list(reversed(items)))

    prompt = json.dumps(body_of(route)["messages"])
    assert f"[{CANDIDATE_LIMIT}] (" in prompt and f"[{CANDIDATE_LIMIT + 1}] (" not in prompt
    assert (
        f"Story {CANDIDATE_LIMIT + 1}" not in prompt and "Story 1 " in prompt or "Story 1" in prompt
    )
    assert (
        selection.candidates == CANDIDATE_LIMIT + 15 and selection.items[0].item_id == items[0].id
    )


@respx.mock
async def test_nonsense_in_the_answer_is_ignored(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    show.items_per_episode = 2
    items = await add_items(db_session, show, 6)
    respx.post(OPENROUTER_URL).mock(
        return_value=answer(
            pick(99, 9),  # no such item
            pick(0, 9),  # numbering starts at 1
            pick(2, 14, "Over the top."),  # score is clamped
            pick(2, 8),  # used twice
            pick(3, -4, supporting=[3, 2, 42, 5, 5]),  # itself, a main item, unknown, a duplicate
            pick(6, 3),  # beyond the limit of 2
        )
    )

    selection = await rank(db_session, show, items)

    assert [p.item_id for p in selection.items] == [items[1].id, items[2].id]
    assert [p.score for p in selection.items] == [10.0, 0.0]
    assert selection.items[1].supporting_item_ids == (items[4].id,)  # only the valid, unused one


@respx.mock
async def test_a_missing_reason_gets_a_default(db_session: AsyncSession, admin_user: User) -> None:
    show = await make_show(db_session, admin_user)
    items = await add_items(db_session, show, 2)
    respx.post(OPENROUTER_URL).mock(return_value=answer({"item": 1}))

    selection = await rank(db_session, show, items)

    assert (
        selection.items[0].reason == "Chosen by the editor model."
        and selection.items[0].score == 5.0
    )


async def test_no_items_means_no_model_call(db_session: AsyncSession, admin_user: User) -> None:
    show = await make_show(db_session, admin_user)

    with respx.mock:
        route = respx.post(OPENROUTER_URL).mock(return_value=answer(pick(1)))
        selection = await rank(db_session, show, [])

    assert selection.items == [] and not route.called


# --- falling back to recency ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        pytest.param(
            httpx.Response(500, json={"error": {"message": "down"}}),
            "language model failed",
            id="error",
        ),
        pytest.param(
            httpx.Response(401, json={"error": {"message": "key"}}),
            "language model failed",
            id="auth",
        ),
        pytest.param(answer(pick(99), pick(0)), "no usable selection", id="nonsense"),
        pytest.param(answer(), "no usable selection", id="empty"),
    ],
)
@respx.mock
async def test_the_newest_items_are_used_when_the_model_cannot_help(
    response: httpx.Response, reason: str, db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    show.items_per_episode = 3
    items = await add_items(db_session, show, 6)
    respx.post(OPENROUTER_URL).mock(return_value=response)

    with structlog.testing.capture_logs() as logs:
        selection = await rank(db_session, show, list(reversed(items)), run_id=uuid.UUID(int=9))

    assert selection.used_fallback and reason in (selection.fallback_reason or "")
    assert [p.item_id for p in selection.items] == [items[0].id, items[1].id, items[2].id]
    assert all(p.score == 0.0 and "Most recent" in p.reason for p in selection.items)
    warning = next(e for e in logs if e["event"] == "ranking_fallback")
    assert warning["run_id"] == str(uuid.UUID(int=9)) and reason in warning["reason"]


async def test_the_fallback_when_no_model_is_configured(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    items = await add_items(db_session, show, 3)

    selection = await rank_items(
        CredentialResolver(db_session, make_settings()), make_settings(), show, items
    )

    assert selection.used_fallback and "No language model" in (selection.fallback_reason or "")
    assert len(selection.items) == 3


async def test_the_fallback_when_the_provider_has_no_key(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    items = await add_items(db_session, show, 3)
    cfg = make_settings(default_llm_provider="openai", default_llm_model="gpt-x")

    selection = await rank_items(CredentialResolver(db_session, cfg), cfg, show, items)

    assert selection.used_fallback and "not set up" in (selection.fallback_reason or "")


@respx.mock
async def test_a_show_uses_its_own_model_before_the_default(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    show.llm_provider, show.llm_model = "openrouter", "vendor/own-pick"
    items = await add_items(db_session, show, 2)
    route = respx.post(OPENROUTER_URL).mock(return_value=answer(pick(1)))

    await rank(db_session, show, items)

    assert body_of(route)["model"] == "vendor/own-pick"


# --- reservation ---------------------------------------------------------------------------


async def held_by(session: AsyncSession, show: Show) -> dict[str, uuid.UUID | None]:
    rows = await session.execute(
        select(Item.title, Item.reserved_run_id).where(Item.show_id == show.id)
    )
    return dict(rows.all())


async def test_reserving_holds_items_for_one_run_only(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    items = await add_items(db_session, show, 5)
    first, second = (
        await add_run(db_session, show),
        await add_run(db_session, show, RunStatus.AWAITING_REVIEW),
    )
    ids = [i.id for i in items]

    won = await reserve_items(db_session, show, first.id, ids[:3])
    lost = await reserve_items(db_session, show, second.id, ids[1:5])

    assert won == set(ids[:3])
    assert lost == set(ids[3:5])  # 1 and 2 were already held by the first run
    held = await held_by(db_session, show)
    assert held["Story 1"] == first.id and held["Story 4"] == second.id


async def test_reserving_again_for_the_same_run_is_a_no_op(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    items = await add_items(db_session, show, 2)
    run = await add_run(db_session, show)

    first = await reserve_items(db_session, show, run.id, [i.id for i in items])
    again = await reserve_items(db_session, show, run.id, [i.id for i in items])

    assert first == again == {i.id for i in items}
    assert await reserve_items(db_session, show, run.id, []) == set()


async def test_used_items_and_other_shows_items_cannot_be_reserved(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    other_user = await make_user(db_session, "other@example.com")
    elsewhere = await make_show(db_session, other_user, slug="elsewhere")
    mine = await add_items(db_session, show, 2)
    theirs = await add_items(db_session, elsewhere, 1, prefix="Theirs")
    episode = Episode(user_id=admin_user.id, show_id=show.id, title="Ep")
    db_session.add(episode)
    await db_session.flush()
    mine[0].used_in_episode_id = episode.id
    run = await add_run(db_session, show)

    got = await reserve_items(db_session, show, run.id, [mine[0].id, mine[1].id, theirs[0].id])

    assert got == {mine[1].id}


async def test_release_gives_everything_back(db_session: AsyncSession, admin_user: User) -> None:
    show = await make_show(db_session, admin_user)
    items = await add_items(db_session, show, 4)
    first, second = (
        await add_run(db_session, show),
        await add_run(db_session, show, RunStatus.AWAITING_REVIEW),
    )
    await reserve_items(db_session, show, first.id, [items[0].id, items[1].id])
    await reserve_items(db_session, show, second.id, [items[2].id])

    released = await release_items(db_session, admin_user.id, first.id)

    assert released == 2
    held = await held_by(db_session, show)
    assert held["Story 1"] is None and held["Story 2"] is None and held["Story 3"] == second.id
    assert await release_items(db_session, admin_user.id, first.id) == 0
    # released items can be taken by another run
    assert await reserve_items(db_session, show, second.id, [items[0].id]) == {items[0].id}


async def test_committing_turns_holds_into_use_by_an_episode(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    items = await add_items(db_session, show, 3)
    run = await add_run(db_session, show)
    await reserve_items(db_session, show, run.id, [items[0].id, items[1].id])
    episode = Episode(user_id=admin_user.id, show_id=show.id, title="Ep")
    db_session.add(episode)
    await db_session.flush()

    assert await commit_items(db_session, admin_user.id, run.id, episode.id) == 2

    for item in items:
        await db_session.refresh(item)
    assert [i.used_in_episode_id for i in items] == [episode.id, episode.id, None]
    assert all(i.reserved_run_id is None for i in items)
    assert [i.id for i in await available_items(db_session, show)] == [items[2].id]


async def test_available_items_skip_held_and_used_but_include_the_runs_own(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    items = await add_items(db_session, show, 4)
    mine, theirs = (
        await add_run(db_session, show),
        await add_run(db_session, show, RunStatus.AWAITING_REVIEW),
    )
    await reserve_items(db_session, show, mine.id, [items[0].id])
    await reserve_items(db_session, show, theirs.id, [items[1].id])

    for_me = {i.id for i in await available_items(db_session, show, mine.id)}
    for_nobody = {i.id for i in await available_items(db_session, show)}

    assert for_me == {items[0].id, items[2].id, items[3].id}
    assert for_nobody == {items[2].id, items[3].id}


@respx.mock
async def test_selecting_for_a_run_reserves_the_choice_and_hides_it_from_other_runs(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    show.items_per_episode = 2
    items = await add_items(db_session, show, 6)
    first, second = (
        await add_run(db_session, show),
        await add_run(db_session, show, RunStatus.AWAITING_REVIEW),
    )
    cfg = configured()
    resolver = CredentialResolver(db_session, cfg)
    respx.post(OPENROUTER_URL).mock(
        side_effect=[answer(pick(1, supporting=[2]), pick(3)), answer(pick(1), pick(2))]
    )

    one = await select_for_run(db_session, resolver, cfg, show, first.id)
    two = await select_for_run(db_session, resolver, cfg, show, second.id)

    assert [p.item_id for p in one.items] == [items[0].id, items[2].id]
    assert one.items[0].supporting_item_ids == (items[1].id,)
    held = await held_by(db_session, show)
    assert {t for t, run in held.items() if run == first.id} == {"Story 1", "Story 2", "Story 3"}
    # the second run saw only what was left (items 4, 5, 6 -> numbered 1..3 in its prompt)
    assert [p.item_id for p in two.items] == [items[3].id, items[4].id]
    assert not set(one.reserved_ids) & set(two.reserved_ids)


@respx.mock
async def test_a_concurrent_run_taking_a_pick_makes_the_ranking_run_again(
    db_session: AsyncSession, admin_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    show = await make_show(db_session, admin_user)
    show.items_per_episode = 2
    items = await add_items(db_session, show, 5)
    mine, rival = (
        await add_run(db_session, show),
        await add_run(db_session, show, RunStatus.AWAITING_REVIEW),
    )
    cfg = configured()
    route = respx.post(OPENROUTER_URL).mock(
        side_effect=[answer(pick(1), pick(2)), answer(pick(1), pick(2))]
    )
    real_reserve = ranking.reserve_items
    calls = {"n": 0}

    async def rival_strikes_first(
        session: AsyncSession, show: Show, run_id: uuid.UUID, ids: list[uuid.UUID]
    ) -> set[uuid.UUID]:
        calls["n"] += 1
        if calls["n"] == 1:  # between ranking and reserving, the rival takes item 1
            await real_reserve(session, show, rival.id, [items[0].id])
        return await real_reserve(session, show, run_id, ids)

    monkeypatch.setattr(ranking, "reserve_items", rival_strikes_first)

    selection = await select_for_run(
        db_session, CredentialResolver(db_session, cfg), cfg, show, mine.id
    )

    assert route.call_count == 2
    assert [p.item_id for p in selection.items] == [items[1].id, items[2].id]  # items 2 and 3
    held = await held_by(db_session, show)
    assert {t for t, run in held.items() if run == mine.id} == {"Story 2", "Story 3"}
    assert held["Story 1"] == rival.id  # the failed attempt left nothing behind
    assert not selection.used_fallback


@respx.mock
async def test_after_repeated_conflicts_the_newest_available_items_are_taken(
    db_session: AsyncSession, admin_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    show = await make_show(db_session, admin_user)
    show.items_per_episode = 2
    items = await add_items(db_session, show, 4)
    mine, rival = (
        await add_run(db_session, show),
        await add_run(db_session, show, RunStatus.AWAITING_REVIEW),
    )
    await reserve_items(db_session, show, rival.id, [items[0].id])
    cfg = configured()

    async def stubborn(*args: object, **kwargs: object) -> RankedSelection:
        # always chooses the item the rival holds
        return RankedSelection([RankedItem(items[0].id, 9.0, "Hope")], candidates=4)

    monkeypatch.setattr(ranking, "rank_items", stubborn)

    selection = await select_for_run(
        db_session, CredentialResolver(db_session, cfg), cfg, show, mine.id
    )

    assert selection.used_fallback and "another run" in (selection.fallback_reason or "")
    assert [p.item_id for p in selection.items] == [items[1].id, items[2].id]


async def test_nothing_available_is_an_empty_selection(
    db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    run = await add_run(db_session, show)
    cfg = configured()

    selection = await select_for_run(
        db_session, CredentialResolver(db_session, cfg), cfg, show, run.id
    )

    assert selection.items == [] and selection.merged_groups == []


# --- real concurrency: two connections, committed rows ----------------------------------------


async def test_two_runs_reserving_at_the_same_time_never_share_an_item(engine: object) -> None:
    from sqlalchemy.ext.asyncio import AsyncEngine

    assert isinstance(engine, AsyncEngine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tag = uuid.uuid4().hex[:8]
    async with factory() as setup:
        user = await make_user(setup, f"race-{tag}@example.com")
        show = await make_show(setup, user, slug=f"race-{tag}")
        items = await add_items(setup, show, 40)
        runs = [await add_run(setup, show), await add_run(setup, show, RunStatus.AWAITING_REVIEW)]
        await setup.commit()
        ids = [i.id for i in items]
        run_ids = [r.id for r in runs]
        user_id = user.id
    try:

        async def attempt(run_id: uuid.UUID, wanted: list[uuid.UUID]) -> set[uuid.UUID]:
            async with factory() as session:
                fresh = await session.get(Show, show.id)
                assert fresh is not None
                return await reserve_items(session, fresh, run_id, wanted)

        results = await asyncio.gather(attempt(run_ids[0], ids[:30]), attempt(run_ids[1], ids[10:]))

        assert not results[0] & results[1]  # nothing was reserved twice
        assert results[0] | results[1] == set(ids)  # and nothing was lost
        async with factory() as check:
            held = dict((await check.execute(select(Item.id, Item.reserved_run_id))).all())
            owners = {held[i] for i in ids}
            assert owners == set(run_ids)
            assert all((held[i] == run_ids[0]) == (i in results[0]) for i in ids)
    finally:
        async with factory() as cleanup:
            owner = await cleanup.get(User, user_id)
            if owner is not None:
                await cleanup.delete(owner)
                await cleanup.commit()
