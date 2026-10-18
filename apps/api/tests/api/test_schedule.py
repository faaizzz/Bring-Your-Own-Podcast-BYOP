from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import User
from tests.models.factories import make_show, make_user

DAILY = {"schedule_kind": "daily", "schedule_time": "09:00:00", "timezone": "UTC"}


async def create(authed: AsyncClient, **fields: object) -> dict[str, str]:
    body = {"title": "Daily AI", "topic": "AI", **fields}
    response = await authed.post("/api/shows", json=body)
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


async def test_a_scheduled_show_gets_its_next_run_on_creation(authed: AsyncClient) -> None:
    show = await create(authed, **DAILY)

    next_run = parse(show["next_run_at"])
    assert next_run > datetime.now(UTC)
    assert next_run - datetime.now(UTC) <= timedelta(days=1, minutes=1)
    assert (next_run.hour, next_run.minute) == (9, 0)


async def test_a_manual_show_has_no_next_run(authed: AsyncClient) -> None:
    assert (await create(authed))["next_run_at"] is None


async def test_editing_the_schedule_moves_the_next_run(authed: AsyncClient) -> None:
    show = await create(authed, **DAILY)

    weekly = await authed.patch(
        f"/api/shows/{show['id']}",
        json={"schedule_kind": "weekly", "schedule_weekday": 2, "schedule_time": "18:30:00"},
    )
    assert weekly.status_code == 200, weekly.text
    moved = parse(weekly.json()["next_run_at"])
    assert (moved.weekday(), moved.hour, moved.minute) == (2, 18, 30)

    manual = await authed.patch(f"/api/shows/{show['id']}", json={"schedule_kind": "manual"})
    assert manual.json()["next_run_at"] is None


async def test_changing_the_time_zone_moves_the_next_run(authed: AsyncClient) -> None:
    show = await create(authed, **DAILY)
    before = parse(show["next_run_at"])

    response = await authed.patch(f"/api/shows/{show['id']}", json={"timezone": "Asia/Tokyo"})

    after = parse(response.json()["next_run_at"])
    assert after != before
    assert (after.hour, after.minute) == (0, 0)  # 09:00 in Tokyo is 00:00 UTC


async def test_other_edits_leave_the_next_run_alone(authed: AsyncClient) -> None:
    show = await create(authed, **DAILY)

    response = await authed.patch(f"/api/shows/{show['id']}", json={"title": "Renamed"})

    assert response.json()["next_run_at"] == show["next_run_at"]


async def test_pausing_stops_the_schedule_and_resuming_restarts_it(authed: AsyncClient) -> None:
    show = await create(authed, **DAILY)

    paused = await authed.post(f"/api/shows/{show['id']}/pause")
    assert paused.status_code == 200
    assert paused.json()["paused"] is True and paused.json()["next_run_at"] is None

    resumed = await authed.post(f"/api/shows/{show['id']}/resume")
    assert resumed.json()["paused"] is False
    assert parse(resumed.json()["next_run_at"]) > datetime.now(UTC)


async def test_editing_the_paused_flag_does_the_same(authed: AsyncClient) -> None:
    show = await create(authed, **DAILY)

    paused = await authed.patch(f"/api/shows/{show['id']}", json={"paused": True})
    assert paused.json()["next_run_at"] is None
    resumed = await authed.patch(f"/api/shows/{show['id']}", json={"paused": False})
    assert resumed.json()["next_run_at"] is not None


async def test_pausing_a_manual_show_is_harmless(authed: AsyncClient) -> None:
    show = await create(authed)

    response = await authed.post(f"/api/shows/{show['id']}/pause")

    assert response.json()["paused"] is True and response.json()["next_run_at"] is None


@pytest.mark.parametrize("action", ["pause", "resume"])
async def test_unknown_and_foreign_shows_are_404(
    authed: AsyncClient, db_session: AsyncSession, action: str
) -> None:
    other: User = await make_user(db_session, "other@example.com")
    foreign = await make_show(db_session, other, "foreign")

    assert (await authed.post(f"/api/shows/{foreign.id}/{action}")).status_code == 404
    assert (
        await authed.post("/api/shows/00000000-0000-0000-0000-000000000000/" + action)
    ).status_code == 404


@pytest.mark.parametrize("action", ["pause", "resume"])
async def test_pause_and_resume_need_a_session(client: AsyncClient, action: str) -> None:
    response = await client.post(f"/api/shows/00000000-0000-0000-0000-000000000000/{action}")
    assert response.status_code == 401
