from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import get_settings
from byop.models import Episode, Run, Show, User
from byop.models.enums import EpisodeStatus, RunStatus, RunTrigger
from tests.helpers import make_settings
from tests.models.factories import make_show, make_user

OPENROUTER_MODELS = "https://openrouter.ai/api/v1/models"
MODEL_LIST = {"data": [{"id": "anthropic/claude-sonnet", "name": "Sonnet", "context_length": 1}]}
NEW = {"title": "Daily AI News", "topic": "Artificial intelligence"}


def configure(app: FastAPI, **overrides: object) -> None:
    app.dependency_overrides[get_settings] = lambda: make_settings(**overrides)


async def create(authed: AsyncClient, **fields: object) -> dict[str, object]:
    response = await authed.post("/api/shows", json={**NEW, **fields})
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


# --- create ---------------------------------------------------------------


async def test_create_applies_defaults_and_generates_a_slug(authed: AsyncClient) -> None:
    show = await create(authed)

    assert show["slug"] == "daily-ai-news"
    assert show["slug_locked"] is False
    assert show["language"] == "en"
    assert show["target_minutes"] == 10
    assert show["items_per_episode"] == 5
    assert show["style"] == "news_briefing"
    assert show["schedule_kind"] == "manual"
    assert show["timezone"] == "UTC"
    assert show["episode_count"] == 0
    assert show["last_run_status"] is None
    assert show["next_run_at"] is None
    assert show["warnings"] == []
    assert show["llm_provider"] is None


async def test_slugs_are_unique_across_the_instance(
    authed: AsyncClient, db_session: AsyncSession
) -> None:
    other = await make_user(db_session, "other@example.com")
    await make_show(db_session, other, slug="daily-ai-news")

    first = await create(authed)
    second = await create(authed)

    assert first["slug"] == "daily-ai-news-2"
    assert second["slug"] == "daily-ai-news-3"


async def test_slug_handles_accents_symbols_and_empty_titles(authed: AsyncClient) -> None:
    assert (await create(authed, title="Café  Société — 100% Ça!"))["slug"] == "cafe-societe-100-ca"
    assert (await create(authed, title="日本語"))["slug"] == "show"


async def test_explicit_slug_is_used_and_must_be_free(authed: AsyncClient) -> None:
    assert (await create(authed, slug="my-show"))["slug"] == "my-show"

    taken = await authed.post("/api/shows", json={**NEW, "slug": "my-show"})
    assert taken.status_code == 409

    for bad in ("My Show", "-lead", "double--dash", "x" * 101):
        response = await authed.post("/api/shows", json={**NEW, "slug": bad})
        assert response.status_code == 422, bad


async def test_create_validates_fields(authed: AsyncClient) -> None:
    bad_payloads: list[dict[str, str | int]] = [
        {"title": "   "},
        {"topic": ""},
        {"language": "english"},
        {"language": "en_US"},
        {"target_minutes": 0},
        {"target_minutes": 61},
        {"items_per_episode": 0},
        {"items_per_episode": 21},
        {"timezone": "Mars/Base"},
        {"style": "rap_battle"},
        {"feed_email": "not-an-email"},
        {"schedule_kind": "daily"},  # needs a time
        {"schedule_kind": "weekly", "schedule_time": "08:00"},  # needs a weekday
        {"schedule_kind": "monthly", "schedule_time": "08:00"},  # needs a day of the month
        {"schedule_weekday": 7},
        {"schedule_monthday": 0},
    ]
    for payload in bad_payloads:
        response = await authed.post("/api/shows", json={**NEW, **payload})
        assert response.status_code == 422, payload


async def test_create_accepts_valid_bcp47_and_schedules(authed: AsyncClient) -> None:
    show = await create(
        authed,
        language="zh-Hans-CN",
        target_minutes=60,
        items_per_episode=20,
        schedule_kind="weekly",
        schedule_time="08:30:00",
        schedule_weekday=0,
        timezone="Europe/Berlin",
        feed_email="host@example.com",
    )

    assert show["language"] == "zh-Hans-CN"
    assert show["schedule_time"] == "08:30:00"
    assert show["timezone"] == "Europe/Berlin"


async def test_instance_defaults_fill_model_and_style(app: FastAPI, authed: AsyncClient) -> None:
    configure(
        app,
        default_llm_provider="openrouter",
        default_llm_model="anthropic/claude-sonnet",
        default_show_style="deep_dive",
    )

    show = await create(authed)

    assert (show["llm_provider"], show["llm_model"], show["style"]) == (
        "openrouter",
        "anthropic/claude-sonnet",
        "deep_dive",
    )
    assert show["warnings"] == []  # defaults are not verified against the provider


async def test_blank_defaults_in_the_environment_mean_unset(app: FastAPI) -> None:
    settings = make_settings(default_llm_provider="", default_llm_model="", default_show_style="")

    assert settings.default_llm_provider is None
    assert settings.default_llm_model is None
    assert settings.default_show_style == "news_briefing"


async def test_a_default_model_needs_its_provider(app: FastAPI, authed: AsyncClient) -> None:
    configure(app, default_llm_model="anthropic/claude-sonnet")

    assert (await create(authed))["llm_model"] is None


async def test_explicit_choices_beat_the_defaults(app: FastAPI, authed: AsyncClient) -> None:
    configure(app, default_show_style="deep_dive")

    assert (await create(authed, style="interview"))["style"] == "interview"


# --- model verification -----------------------------------------------------


@respx.mock
async def test_a_listed_model_is_accepted(app: FastAPI, authed: AsyncClient) -> None:
    configure(app, openrouter_api_key=SecretStr("sk-or-env-key-123456"))
    respx.get(OPENROUTER_MODELS).respond(200, json=MODEL_LIST)

    show = await create(authed, llm_provider="openrouter", llm_model="anthropic/claude-sonnet")

    assert show["warnings"] == []
    assert show["llm_model"] == "anthropic/claude-sonnet"


@respx.mock
async def test_an_unknown_model_is_rejected(app: FastAPI, authed: AsyncClient) -> None:
    configure(app, openrouter_api_key=SecretStr("sk-or-env-key-123456"))
    respx.get(OPENROUTER_MODELS).respond(200, json=MODEL_LIST)

    response = await authed.post(
        "/api/shows", json={**NEW, "llm_provider": "openrouter", "llm_model": "nope/none"}
    )

    assert response.status_code == 422
    assert "nope/none" in response.json()["detail"]


async def test_an_unconfigured_provider_only_warns(authed: AsyncClient) -> None:
    show = await create(authed, llm_provider="openai", llm_model="gpt-x")

    assert show["llm_model"] == "gpt-x"
    assert "not configured" in str(show["warnings"])


@respx.mock
async def test_an_unavailable_model_list_only_warns(app: FastAPI, authed: AsyncClient) -> None:
    configure(app, openrouter_api_key=SecretStr("sk-or-env-key-123456"))
    respx.get(OPENROUTER_MODELS).mock(side_effect=httpx.ConnectError("down"))

    show = await create(authed, llm_provider="openrouter", llm_model="anything")

    assert "unavailable" in str(show["warnings"])


async def test_provider_and_model_come_as_a_pair(authed: AsyncClient) -> None:
    for payload in ({"llm_provider": "openai"}, {"llm_model": "gpt-x"}):
        response = await authed.post("/api/shows", json={**NEW, **payload})
        assert response.status_code == 422, payload


# --- read ---------------------------------------------------------------------


async def test_list_has_counts_last_run_and_next_run(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    busy = await make_show(db_session, admin_user, slug="busy")
    quiet = await make_show(db_session, admin_user, slug="quiet")
    busy.next_run_at = datetime(2030, 1, 1, 8, 0, tzinfo=UTC)
    older = Run(
        user_id=admin_user.id,
        show_id=busy.id,
        trigger=RunTrigger.MANUAL,
        status=RunStatus.FAILED,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    newer = Run(
        user_id=admin_user.id,
        show_id=busy.id,
        trigger=RunTrigger.SCHEDULE,
        status=RunStatus.SUCCEEDED,
        created_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    db_session.add_all(
        [older, newer]
        + [Episode(user_id=admin_user.id, show_id=busy.id, title=f"Ep {n}") for n in range(2)]
        + [
            Episode(
                user_id=admin_user.id,
                show_id=busy.id,
                title="Live",
                status=EpisodeStatus.PUBLISHED,
                published_at=datetime(2027, 5, 6, 7, 0, tzinfo=UTC),
            )
        ]
    )
    await db_session.flush()

    response = await authed.get("/api/shows")

    assert response.status_code == 200
    by_slug = {s["slug"]: s for s in response.json()}
    assert by_slug["busy"]["episode_count"] == 3
    assert by_slug["busy"]["last_run_status"] == "succeeded"
    assert by_slug["busy"]["last_episode_at"].startswith("2027-05-06T07:00")
    assert by_slug["quiet"]["last_episode_at"] is None
    assert by_slug["busy"]["next_run_at"].startswith("2030-01-01T08:00")
    assert by_slug["quiet"]["episode_count"] == 0
    assert by_slug["quiet"]["last_run_status"] is None
    assert quiet.id is not None


async def test_get_returns_one_show(authed: AsyncClient) -> None:
    created = await create(authed)

    response = await authed.get(f"/api/shows/{created['id']}")

    assert response.status_code == 200
    assert response.json()["title"] == "Daily AI News"


async def test_unknown_ids_are_404(authed: AsyncClient) -> None:
    missing = "00000000-0000-4000-8000-000000000000"
    assert (await authed.get(f"/api/shows/{missing}")).status_code == 404
    assert (await authed.patch(f"/api/shows/{missing}", json={"title": "x"})).status_code == 404
    assert (await authed.delete(f"/api/shows/{missing}")).status_code == 404
    assert (await authed.get("/api/shows/not-a-uuid")).status_code == 422


# --- ownership ------------------------------------------------------------------


async def test_other_users_shows_are_invisible_and_untouchable(
    authed: AsyncClient, db_session: AsyncSession
) -> None:
    other = await make_user(db_session, "other@example.com")
    theirs = await make_show(db_session, other, slug="theirs")

    assert (await authed.get("/api/shows")).json() == []
    assert (await authed.get(f"/api/shows/{theirs.id}")).status_code == 404
    patch = await authed.patch(f"/api/shows/{theirs.id}", json={"title": "Mine now"})
    assert patch.status_code == 404
    assert (await authed.delete(f"/api/shows/{theirs.id}")).status_code == 404

    await db_session.refresh(theirs)
    assert theirs.title == "Daily AI"
    assert await db_session.get(Show, theirs.id) is not None


# --- update -------------------------------------------------------------------


async def test_patch_changes_only_the_given_fields(authed: AsyncClient) -> None:
    created = await create(authed, description="Original", llm_provider=None)

    response = await authed.patch(
        f"/api/shows/{created['id']}", json={"title": "Weekly AI", "target_minutes": 20}
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["title"], body["target_minutes"], body["description"]) == (
        "Weekly AI",
        20,
        "Original",
    )
    assert body["slug"] == "daily-ai-news"  # a new title does not move the feed URL
    assert body["updated_at"] >= created["updated_at"]


async def test_patch_validates_and_forbids_nulling_required_fields(authed: AsyncClient) -> None:
    created = await create(authed)
    url = f"/api/shows/{created['id']}"

    for payload in (
        {"title": None},
        {"language": None},
        {"target_minutes": None},
        {"target_minutes": 99},
        {"timezone": "Nowhere/Land"},
    ):
        assert (await authed.patch(url, json=payload)).status_code == 422, payload


async def test_patch_can_clear_optional_fields(authed: AsyncClient) -> None:
    created = await create(authed, prompt_override="Be funny", feed_author="Ada")

    response = await authed.patch(
        f"/api/shows/{created['id']}", json={"prompt_override": None, "feed_author": None}
    )

    assert response.json()["prompt_override"] is None
    assert response.json()["feed_author"] is None


async def test_patch_checks_the_schedule_as_a_whole(authed: AsyncClient) -> None:
    created = await create(authed)
    url = f"/api/shows/{created['id']}"

    incomplete = await authed.patch(url, json={"schedule_kind": "daily"})
    assert incomplete.status_code == 422
    assert "time of day" in incomplete.json()["detail"]

    ok = await authed.patch(url, json={"schedule_kind": "daily", "schedule_time": "07:00"})
    assert ok.status_code == 200
    # Removing the time from an existing daily schedule is also incomplete.
    assert (await authed.patch(url, json={"schedule_time": None})).status_code == 422


@respx.mock
async def test_patch_verifies_a_changed_model(app: FastAPI, authed: AsyncClient) -> None:
    configure(app, openrouter_api_key=SecretStr("sk-or-env-key-123456"))
    respx.get(OPENROUTER_MODELS).respond(200, json=MODEL_LIST)
    created = await create(authed)
    url = f"/api/shows/{created['id']}"

    only_provider = await authed.patch(url, json={"llm_provider": "openrouter"})
    unknown = await authed.patch(url, json={"llm_provider": "openrouter", "llm_model": "x/y"})
    fine = await authed.patch(
        url, json={"llm_provider": "openrouter", "llm_model": "anthropic/claude-sonnet"}
    )

    assert only_provider.status_code == 422
    assert unknown.status_code == 422
    assert fine.status_code == 200 and fine.json()["warnings"] == []


async def test_slug_can_change_until_an_episode_is_published(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    created = await create(authed)
    url = f"/api/shows/{created['id']}"

    renamed = await authed.patch(url, json={"slug": "ai-daily"})
    assert renamed.status_code == 200 and renamed.json()["slug"] == "ai-daily"

    other = await make_show(db_session, admin_user, slug="taken")
    clash = await authed.patch(url, json={"slug": other.slug})
    assert clash.status_code == 409

    # A draft does not lock the slug; a published episode does.
    db_session.add(Episode(user_id=admin_user.id, show_id=renamed.json()["id"], title="Draft"))
    await db_session.flush()
    assert (await authed.patch(url, json={"slug": "still-free"})).status_code == 200

    db_session.add(
        Episode(
            user_id=admin_user.id,
            show_id=renamed.json()["id"],
            title="Live",
            status=EpisodeStatus.PUBLISHED,
            published_at=datetime(2026, 3, 1, tzinfo=UTC),
        )
    )
    await db_session.flush()
    locked = await authed.patch(url, json={"slug": "too-late"})
    assert locked.status_code == 409
    assert "feed URL" in locked.json()["detail"]
    same = await authed.patch(url, json={"slug": "still-free", "title": "Renamed"})
    assert same.status_code == 200
    assert same.json()["slug_locked"] is True


# --- delete -------------------------------------------------------------------


async def test_delete_removes_the_show_its_children_and_its_media(
    app: FastAPI,
    authed: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    tmp_path: Path,
) -> None:
    configure(app, media_root=str(tmp_path))
    created = await create(authed)
    show_id = str(created["id"])
    db_session.add(Episode(user_id=admin_user.id, show_id=show_id, title="Ep"))
    await db_session.flush()
    mine = tmp_path / "shows" / show_id / "episodes"
    mine.mkdir(parents=True)
    (mine / "ep1.mp3").write_bytes(b"audio")
    (tmp_path / "shows" / show_id / "cover.jpg").write_bytes(b"img")
    elsewhere = tmp_path / "shows" / "another-show"
    elsewhere.mkdir()
    (elsewhere / "keep.mp3").write_bytes(b"keep")

    response = await authed.delete(f"/api/shows/{show_id}")

    assert response.status_code == 204
    assert (await authed.get(f"/api/shows/{show_id}")).status_code == 404
    assert not (tmp_path / "shows" / show_id).exists()
    assert (elsewhere / "keep.mp3").exists()
    remaining = await db_session.scalar(select(func.count()).select_from(Episode))
    assert remaining == 0


async def test_delete_works_when_the_show_has_no_media(
    app: FastAPI, authed: AsyncClient, tmp_path: Path
) -> None:
    configure(app, media_root=str(tmp_path))
    created = await create(authed)

    assert (await authed.delete(f"/api/shows/{created['id']}")).status_code == 204


async def test_requires_a_session(client: AsyncClient) -> None:
    assert (await client.get("/api/shows")).status_code == 401
    assert (await client.post("/api/shows", json=NEW)).status_code == 401
