from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import get_settings
from byop.models import Episode, Run, Show, UsageEvent, User
from byop.models.enums import (
    CostSource,
    EpisodeStatus,
    RunStatus,
    RunTrigger,
    ScheduleKind,
    UsageKind,
)
from tests.helpers import make_settings
from tests.models.factories import make_show, make_user


def ago(**delta: int) -> datetime:
    return datetime.now(UTC) - timedelta(**delta)


async def run_of(
    session: AsyncSession,
    user: User,
    show: Show,
    status: RunStatus,
    *,
    created: datetime | None = None,
    error: str | None = None,
    progress: int = 0,
) -> Run:
    run = Run(
        user_id=user.id,
        show_id=show.id,
        trigger=RunTrigger.MANUAL,
        status=status,
        error=error,
        progress=progress,
        stage="tts" if status is RunStatus.RUNNING else None,
        created_at=created or ago(hours=1),
    )
    session.add(run)
    await session.flush()
    return run


async def get(authed: AsyncClient) -> dict[str, Any]:
    response = await authed.get("/api/dashboard")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_an_empty_instance_asks_for_onboarding(authed: AsyncClient, app: FastAPI) -> None:
    app.dependency_overrides[get_settings] = lambda: make_settings()

    body = await get(authed)

    assert body["onboarding"] == {
        "provider_configured": False,
        "voice_configured": False,
        "show_created": False,
        "episode_generated": False,
    }
    assert (body["shows"], body["episodes_this_month"], body["drafts_to_review"]) == (0, 0, 0)
    assert Decimal(body["spend_this_month_usd"]) == 0 and body["success_rate"] is None
    assert body["upcoming"] == [] and body["active_runs"] == []
    assert body["recent_failures"] == [] and body["latest_episodes"] == []


async def test_onboarding_follows_the_providers_the_show_and_the_first_episode(
    authed: AsyncClient, app: FastAPI, db_session: AsyncSession, admin_user: User
) -> None:
    app.dependency_overrides[get_settings] = lambda: make_settings(
        openrouter_api_key=SecretStr("sk-or-test-0123456789")
    )
    assert (await get(authed))["onboarding"]["provider_configured"] is True

    show = await make_show(db_session, admin_user)
    assert (await get(authed))["onboarding"] == {
        "provider_configured": True,
        "voice_configured": True,  # OpenRouter speaks too
        "show_created": True,
        "episode_generated": False,
    }

    db_session.add(Episode(user_id=admin_user.id, show_id=show.id, title="First"))
    await db_session.flush()
    assert (await get(authed))["onboarding"]["episode_generated"] is True


async def test_a_voice_provider_key_completes_the_voice_step(
    authed: AsyncClient, app: FastAPI
) -> None:
    app.dependency_overrides[get_settings] = lambda: make_settings(
        elevenlabs_api_key=SecretStr("xi-test-0123456789")
    )
    assert (await get(authed))["onboarding"]["voice_configured"] is True


async def test_tiles_count_this_month_and_the_success_rate_of_the_last_30_days(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    now = datetime.now(UTC)
    first_of_month = now.replace(day=1, hour=0, minute=0, second=1, microsecond=0)
    last_month = first_of_month - timedelta(days=3)
    for status, created in (
        (RunStatus.SUCCEEDED, ago(days=1)),
        (RunStatus.AWAITING_REVIEW, ago(days=2)),
        (RunStatus.SUCCEEDED, ago(days=3)),
        (RunStatus.FAILED, ago(days=4)),
        (RunStatus.CANCELLED, ago(days=5)),  # neither a success nor a failure
        (RunStatus.FAILED, ago(days=40)),  # too old to count
    ):
        await run_of(db_session, admin_user, show, status, created=created)
    db_session.add_all(
        [
            Episode(
                user_id=admin_user.id,
                show_id=show.id,
                title="Draft",
                created_at=first_of_month,
            ),
            Episode(
                user_id=admin_user.id,
                show_id=show.id,
                title="Published",
                status=EpisodeStatus.PUBLISHED,
                created_at=first_of_month,
            ),
            Episode(user_id=admin_user.id, show_id=show.id, title="Old", created_at=last_month),
            UsageEvent(
                user_id=admin_user.id,
                show_id=show.id,
                kind=UsageKind.LLM,
                provider="openrouter",
                cost_usd=Decimal("0.25"),
                cost_source=CostSource.PROVIDER,
                created_at=first_of_month,
            ),
            UsageEvent(
                user_id=admin_user.id,
                show_id=show.id,
                kind=UsageKind.LLM,
                provider="openrouter",
                cost_usd=Decimal("9"),
                cost_source=CostSource.PROVIDER,
                created_at=last_month,
            ),
        ]
    )
    await db_session.flush()

    body = await get(authed)

    assert body["shows"] == 1 and body["episodes_this_month"] == 2
    assert Decimal(body["spend_this_month_usd"]) == Decimal("0.25")
    assert body["finished_runs_30d"] == 4 and body["success_rate"] == 0.75
    assert body["drafts_to_review"] == 2  # "Draft" and "Old" are both still drafts


async def test_upcoming_runs_cover_the_next_week_for_active_scheduled_shows(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    soon = await make_show(db_session, admin_user, "soon")
    soon.title, soon.schedule_kind = "Soon", ScheduleKind.DAILY
    soon.next_run_at = datetime.now(UTC) + timedelta(hours=3)
    later = await make_show(db_session, admin_user, "later")
    later.title, later.schedule_kind = "Later", ScheduleKind.WEEKLY
    later.next_run_at = datetime.now(UTC) + timedelta(days=6)
    far = await make_show(db_session, admin_user, "far")
    far.schedule_kind, far.next_run_at = (
        ScheduleKind.MONTHLY,
        datetime.now(UTC) + timedelta(days=20),
    )
    paused = await make_show(db_session, admin_user, "paused")
    paused.schedule_kind, paused.paused = ScheduleKind.DAILY, True
    paused.next_run_at = datetime.now(UTC) + timedelta(hours=1)
    manual = await make_show(db_session, admin_user, "manual")
    manual.next_run_at = datetime.now(UTC) + timedelta(hours=1)
    await db_session.flush()

    body = await get(authed)

    assert [u["show_title"] for u in body["upcoming"]] == ["Soon", "Later"]


async def test_active_runs_carry_their_progress(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    run = await run_of(db_session, admin_user, show, RunStatus.RUNNING, progress=62)

    (active,) = (await get(authed))["active_runs"]

    assert active["id"] == str(run.id) and active["show_title"] == "Daily AI"
    assert (active["status"], active["stage"], active["progress"]) == ("running", "tts", 62)


async def test_a_failure_stays_until_the_show_runs_again(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    broken = await make_show(db_session, admin_user, "broken")
    broken.title = "Broken"
    fixed = await make_show(db_session, admin_user, "fixed")
    fixed.title = "Fixed"
    busy = await make_show(db_session, admin_user, "busy")
    busy.title = "Busy"
    old = await make_show(db_session, admin_user, "old")
    await run_of(
        db_session, admin_user, broken, RunStatus.FAILED, created=ago(hours=2), error="boom"
    )
    await run_of(db_session, admin_user, fixed, RunStatus.FAILED, created=ago(hours=5), error="old")
    await run_of(db_session, admin_user, fixed, RunStatus.AWAITING_REVIEW, created=ago(hours=1))
    await run_of(db_session, admin_user, busy, RunStatus.FAILED, created=ago(hours=4), error="x")
    await run_of(db_session, admin_user, busy, RunStatus.RUNNING, created=ago(hours=3))
    await run_of(
        db_session, admin_user, old, RunStatus.FAILED, created=ago(days=9), error="ancient"
    )

    failures = (await get(authed))["recent_failures"]

    # "Fixed" ran again after its failure and "Old" is more than a week old; "Busy" failed and
    # its newer run is the active one, so it is not a failure either.
    assert [f["show_title"] for f in failures] == ["Broken"]
    assert failures[0]["error"] == "boom" and failures[0]["can_retry"] is True


async def test_retry_is_offered_only_when_the_show_has_nothing_running(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    failed = await run_of(
        db_session, admin_user, show, RunStatus.FAILED, created=ago(hours=3), error="x"
    )

    (failure,) = (await get(authed))["recent_failures"]
    assert failure["run_id"] == str(failed.id) and failure["can_retry"] is True

    # A show that is working cannot have a failure that is also its newest run, so retry is
    # offered exactly when the failure is the latest thing that happened.
    await run_of(db_session, admin_user, show, RunStatus.QUEUED, created=ago(hours=1))
    assert (await get(authed))["recent_failures"] == []


async def test_the_latest_episodes_come_with_audio_and_newest_first(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)
    base = datetime(2026, 5, 1, tzinfo=UTC)
    for n in range(7):
        db_session.add(
            Episode(
                user_id=admin_user.id,
                show_id=show.id,
                title=f"Episode {n}",
                created_at=base + timedelta(days=n),
                audio_key=f"k/{n}" if n != 5 else None,
                duration_s=100 + n,
            )
        )
    await db_session.flush()

    episodes = (await get(authed))["latest_episodes"]

    assert [e["title"] for e in episodes] == [f"Episode {n}" for n in (6, 5, 4, 3, 2)]
    assert (
        episodes[0]["audio_url"].startswith("/api/episodes/")
        and "/audio?v=" in episodes[0]["audio_url"]
    )
    assert episodes[1]["audio_url"] is None and episodes[0]["duration_s"] == 106
    assert episodes[0]["show_title"] == "Daily AI"


async def test_other_users_data_is_invisible(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    other = await make_user(db_session, "other@example.com")
    theirs = await make_show(db_session, other, "theirs")
    await run_of(db_session, other, theirs, RunStatus.RUNNING)
    await run_of(db_session, other, theirs, RunStatus.FAILED, created=ago(hours=9), error="x")
    db_session.add(Episode(user_id=other.id, show_id=theirs.id, title="Secret"))
    await db_session.flush()

    body = await get(authed)

    assert body["shows"] == 0 and body["active_runs"] == [] and body["latest_episodes"] == []
    assert body["finished_runs_30d"] == 0 and body["recent_failures"] == []


async def test_requires_a_session(client: AsyncClient) -> None:
    assert (await client.get("/api/dashboard")).status_code == 401
