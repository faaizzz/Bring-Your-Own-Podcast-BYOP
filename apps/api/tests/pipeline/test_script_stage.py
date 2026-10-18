import json

import httpx
import pytest
import respx
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings
from byop.models import Episode, Item, Run, Show, Speaker, User
from byop.models.enums import EpisodeStatus, EventLevel, RunStatus
from byop.pipeline.errors import TransientStageError
from byop.pipeline.orchestrator import Stage, StageResult, run_stage
from byop.pipeline.stages import script as script_stage
from byop.providers.llm import LLMError
from byop.services import runs as run_service
from tests.helpers import make_settings
from tests.models.factories import make_show
from tests.providers.llm.helpers import OPENROUTER_URL, body_of, completion

WORDS = " ".join(["word"] * 45)  # three of these segments fit a one-minute target


def settings() -> Settings:
    return make_settings(
        openrouter_api_key=SecretStr("sk-or-test-key-123456"),
        default_llm_provider="openrouter",
        default_llm_model="vendor/model",
    )


def reply(**overrides: object) -> httpx.Response:
    script: dict[str, object] = {
        "title": "Oceans and bikes",
        "description": "Sonar maps and cycling lanes.",
        "segments": [
            {"speaker": "Alex", "text": f"Welcome. {WORDS}", "kind": "intro", "item_ids": []},
            {"speaker": "Sam", "text": f"Sonar. {WORDS}", "kind": "story", "item_ids": [1]},
            {"speaker": "Alex", "text": f"Bikes. {WORDS}", "kind": "story", "item_ids": [2]},
        ],
        **overrides,
    }
    return httpx.Response(200, json=completion(json.dumps(script)))


async def prepare(
    session: AsyncSession,
    user: User,
    *,
    speakers: bool = True,
    selection: bool = True,
    language: str = "en",
) -> tuple[Show, Run, list[Item]]:
    show = await make_show(session, user)
    show.target_minutes = 1
    show.language = language
    items = [
        Item(
            user_id=user.id,
            show_id=show.id,
            canonical_url=f"https://e.com/{n}",
            content_hash=str(n) * 64,
            title=f"Story {n}",
            summary=f"Details of story {n}.",
        )  # fmt: skip
        for n in (1, 2, 3)
    ]
    session.add_all(items)
    if speakers:
        voice = {"tts_provider": "kokoro", "user_id": user.id, "show_id": show.id}
        session.add_all(
            [
                Speaker(position=0, name="Alex", persona="The lead.", voice_id="a", **voice),
                Speaker(position=1, name="Sam", persona="The co-host.", voice_id="b", **voice),
            ]
        )
    await session.flush()
    run = await run_service.create_run(session, user.id, show.id)
    if selection:
        run.selection = {
            "stories": [
                {"item_id": str(items[0].id), "score": 9, "reason": "Big.",
                 "supporting_item_ids": [str(items[2].id)]},
                {"item_id": str(items[1].id), "score": 7, "reason": "Fun.",
                 "supporting_item_ids": []},
            ]
        }  # fmt: skip
        await session.flush()
    return show, run, items


STAGES = [Stage("script", script_stage.run, 30, 55)]


async def run_it(session: AsyncSession, run: Run, cfg: Settings | None = None) -> StageResult:
    return await run_stage(session, cfg or settings(), run.id, "script", stages=STAGES)


async def error_of(session: AsyncSession, run: Run) -> str | None:
    await session.refresh(run)
    return run.error


@respx.mock
async def test_the_script_becomes_a_draft_episode_with_title_description_and_script(
    db_session: AsyncSession, admin_user: User
) -> None:
    show, run, items = await prepare(db_session, admin_user)
    route = respx.post(OPENROUTER_URL).mock(return_value=reply())

    assert await run_it(db_session, run) is StageResult.DONE

    episode = (await db_session.scalars(select(Episode).where(Episode.run_id == run.id))).one()
    assert (episode.title, episode.description) == (
        "Oceans and bikes",
        "Sonar maps and cycling lanes.",
    )
    assert episode.status is EpisodeStatus.DRAFT
    assert (episode.user_id, episode.show_id) == (admin_user.id, show.id)
    assert episode.audio_key is None
    stored = episode.script
    assert stored is not None
    assert stored["version"] == 1 and stored["speakers"] == ["Alex", "Sam"]
    assert stored["model"] == "vendor/model" and stored["regenerated"] is False
    segments = stored["segments"]
    assert isinstance(segments, list) and [s["kind"] for s in segments] == [
        "intro",
        "story",
        "story",
    ]
    assert segments[1]["item_ids"] == [str(items[0].id)]  # real ids, not prompt numbers
    # the prompt carried the show's data, with the merged coverage attached to story 1
    prompt = json.dumps(body_of(route)["messages"])
    assert "Alex" in prompt and "Story 3" in prompt and "Also reported by" in prompt


@respx.mock
async def test_running_the_stage_again_updates_the_same_draft(
    db_session: AsyncSession, admin_user: User
) -> None:
    _show, run, _items = await prepare(db_session, admin_user)
    respx.post(OPENROUTER_URL).mock(side_effect=[reply(), reply(title="A better title")])

    await run_it(db_session, run)
    await run_it(db_session, run)

    assert await db_session.scalar(select(func.count()).select_from(Episode)) == 1
    assert (await db_session.scalar(select(Episode.title))) == "A better title"


@respx.mock
async def test_a_very_long_title_is_cut_to_fit(db_session: AsyncSession, admin_user: User) -> None:
    _show, run, _items = await prepare(db_session, admin_user)
    respx.post(OPENROUTER_URL).mock(return_value=reply(title="T" * 500))

    await run_it(db_session, run)

    assert len((await db_session.scalar(select(Episode.title))) or "") == 300


@respx.mock
async def test_the_show_prompt_override_language_and_progress_reach_the_model(
    db_session: AsyncSession, admin_user: User
) -> None:
    show, run, _items = await prepare(db_session, admin_user, language="de")
    show.prompt_override = "Always end with a pun."
    route = respx.post(OPENROUTER_URL).mock(return_value=reply())

    await run_it(db_session, run)

    prompt = json.dumps(body_of(route)["messages"], ensure_ascii=False)
    assert "Always end with a pun." in prompt and "**German** (de)" in prompt
    await db_session.refresh(run)
    assert run.progress == 55


@respx.mock
async def test_a_script_outside_the_length_range_is_kept_with_a_warning(
    db_session: AsyncSession, admin_user: User
) -> None:
    _show, run, _items = await prepare(db_session, admin_user)
    short = {"segments": [
        {"speaker": "Alex", "text": "Hi there everyone", "kind": "intro", "item_ids": []},
        {"speaker": "Sam", "text": "Story one told briefly", "kind": "story", "item_ids": [1]},
        {"speaker": "Alex", "text": "Story two told briefly", "kind": "story", "item_ids": [2]},
    ]}  # fmt: skip
    respx.post(OPENROUTER_URL).mock(side_effect=[reply(**short), reply(**short)])

    assert await run_it(db_session, run) is StageResult.DONE

    await db_session.refresh(run, ["events"])
    warnings = [e for e in run.events if e.level is EventLevel.WARNING]
    assert any("too short" in e.message for e in warnings)
    assert any("second attempt" in e.message for e in run.events)


@respx.mock
async def test_an_unusable_script_fails_the_run_with_the_reason(
    db_session: AsyncSession, admin_user: User
) -> None:
    _show, run, _items = await prepare(db_session, admin_user)
    wrong = {"segments": [
        {"speaker": "Narrator", "text": WORDS, "kind": "intro", "item_ids": []},
        {"speaker": "Sam", "text": WORDS, "kind": "story", "item_ids": [1]},
    ]}  # fmt: skip
    respx.post(OPENROUTER_URL).mock(side_effect=[reply(**wrong), reply(**wrong)])

    assert await run_it(db_session, run) is StageResult.FAILED

    error = await error_of(db_session, run)
    assert error is not None and error.startswith(
        "The language model did not write a usable script"
    )
    assert "Unknown speaker" in error and "not covered" in error
    assert run.status is RunStatus.FAILED
    assert await db_session.scalar(select(func.count()).select_from(Episode)) == 0


@pytest.mark.parametrize(
    ("speakers", "selection", "expected"),
    [
        (True, False, "No stories were chosen"),
        (False, True, "The show has no speakers"),
    ],
)
async def test_missing_inputs_fail_the_run_clearly(
    speakers: bool, selection: bool, expected: str, db_session: AsyncSession, admin_user: User
) -> None:
    _show, run, _items = await prepare(
        db_session, admin_user, speakers=speakers, selection=selection
    )

    assert await run_it(db_session, run) is StageResult.FAILED
    assert expected in (await error_of(db_session, run) or "")


async def test_the_stories_must_still_exist(db_session: AsyncSession, admin_user: User) -> None:
    _show, run, items = await prepare(db_session, admin_user)
    for item in items:
        await db_session.delete(item)
    await db_session.flush()

    assert await run_it(db_session, run) is StageResult.FAILED
    assert "gone" in (await error_of(db_session, run) or "")


async def test_without_a_model_or_provider_key_the_run_fails_with_instructions(
    db_session: AsyncSession, admin_user: User
) -> None:
    _show, run, _items = await prepare(db_session, admin_user)
    assert await run_it(db_session, run, make_settings()) is StageResult.FAILED
    assert "No language model is set up" in (await error_of(db_session, run) or "")

    _show2, run2, _ = await prepare_second(db_session, admin_user)
    cfg = make_settings(default_llm_provider="openai", default_llm_model="gpt-x")
    assert await run_it(db_session, run2, cfg) is StageResult.FAILED
    assert "Settings › Integrations" in (await error_of(db_session, run2) or "")


async def prepare_second(session: AsyncSession, user: User) -> tuple[Show, Run, list[Item]]:
    show = await make_show(session, user, slug="second")
    item = Item(
        user_id=user.id, show_id=show.id, canonical_url="https://e.com/s1",
        content_hash="s" * 64, title="S",
    )  # fmt: skip
    session.add_all(
        [
            item,
            Speaker(user_id=user.id, show_id=show.id, position=0, name="Alex",
                    tts_provider="kokoro", voice_id="a"),
        ]
    )  # fmt: skip
    await session.flush()
    run = await run_service.create_run(session, user.id, show.id)
    run.selection = {"stories": [{"item_id": str(item.id), "supporting_item_ids": []}]}
    await session.flush()
    return show, run, [item]


@respx.mock
async def test_a_rejected_key_fails_the_run_but_a_server_error_is_retried(
    db_session: AsyncSession, admin_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _show, run, _items = await prepare(db_session, admin_user)
    respx.post(OPENROUTER_URL).mock(
        return_value=httpx.Response(401, json={"error": {"message": "bad key"}})
    )

    assert await run_it(db_session, run) is StageResult.FAILED
    assert "language model failed" in (await error_of(db_session, run) or "")

    _show2, run2, _ = await prepare_second(db_session, admin_user)

    async def overloaded(*args: object, **kwargs: object) -> object:
        raise LLMError("overloaded", status_code=503)

    monkeypatch.setattr(script_stage, "write_script", overloaded)
    with pytest.raises(TransientStageError, match="overloaded"):
        await run_it(db_session, run2)
    await db_session.refresh(run2)
    assert run2.status is RunStatus.RUNNING  # left for the task to retry


@pytest.mark.parametrize(
    ("status", "transient"),
    [(None, True), (408, True), (429, True), (500, True), (503, True),
     (400, False), (401, False), (403, False), (404, False)],
)  # fmt: skip
def test_which_model_errors_are_worth_retrying(status: int | None, transient: bool) -> None:
    assert script_stage._transient(LLMError("x", status_code=status)) is transient
