import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from kombu.exceptions import OperationalError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from byop.api import runs as runs_api
from byop.models import Run, User
from byop.models.enums import EventLevel, RunStatus, RunTrigger
from byop.pipeline.orchestrator import add_event
from tests.models.factories import make_show, make_user


class Spy:
    def __init__(self) -> None:
        self.enqueued: list[uuid.UUID] = []
        self.revoked: list[str | None] = []


@pytest.fixture
def broker(monkeypatch: pytest.MonkeyPatch) -> Spy:
    """No real broker: record what would be queued and revoked."""
    spy = Spy()

    def enqueue(run_id: uuid.UUID) -> str:
        spy.enqueued.append(run_id)
        return f"task-{len(spy.enqueued)}"

    monkeypatch.setattr(runs_api, "enqueue_run", enqueue)
    monkeypatch.setattr(runs_api, "revoke_quietly", spy.revoked.append)
    return spy


async def new_show(authed: AsyncClient, title: str = "Daily AI") -> str:
    return str((await authed.post("/api/shows", json={"title": title, "topic": "AI"})).json()["id"])


async def finish(
    session: AsyncSession, run_id: str, status: RunStatus = RunStatus.SUCCEEDED
) -> None:
    await session.execute(update(Run).where(Run.id == uuid.UUID(run_id)).values(status=status))


# --- starting ----------------------------------------------------------------------------------


async def test_starting_a_run_queues_it_and_enqueues_the_pipeline(
    authed: AsyncClient, broker: Spy
) -> None:
    show_id = await new_show(authed)

    response = await authed.post(f"/api/shows/{show_id}/runs")

    assert response.status_code == 202
    run = response.json()
    assert run["show_id"] == show_id and run["status"] == "queued" and run["trigger"] == "manual"
    assert run["stage"] is None and run["progress"] == 0 and run["error"] is None
    assert run["started_at"] is None and run["finished_at"] is None
    assert broker.enqueued == [uuid.UUID(run["id"])]
    detail = (await authed.get(f"/api/runs/{run['id']}")).json()
    assert [e["message"] for e in detail["events"]] == ["Run queued"]


async def test_only_one_run_is_active_per_show(
    authed: AsyncClient, db_session: AsyncSession, broker: Spy
) -> None:
    show_id = await new_show(authed)
    other_id = await new_show(authed, "Other")
    first = (await authed.post(f"/api/shows/{show_id}/runs")).json()

    second = await authed.post(f"/api/shows/{show_id}/runs")
    elsewhere = await authed.post(f"/api/shows/{other_id}/runs")

    assert second.status_code == 409 and "already in progress" in second.json()["detail"]
    assert elsewhere.status_code == 202
    assert len(broker.enqueued) == 2  # the rejected one was never queued
    await finish(db_session, first["id"])
    assert (await authed.post(f"/api/shows/{show_id}/runs")).status_code == 202


async def test_unknown_and_foreign_shows_are_404(
    authed: AsyncClient, db_session: AsyncSession, broker: Spy
) -> None:
    other = await make_user(db_session, "other@example.com")
    theirs = await make_show(db_session, other, slug="theirs")

    unknown = await authed.post(f"/api/shows/{uuid.uuid4()}/runs")
    foreign = await authed.post(f"/api/shows/{theirs.id}/runs")

    assert unknown.status_code == 404 and foreign.status_code == 404
    assert broker.enqueued == []


async def test_a_broken_queue_fails_the_run_instead_of_leaving_it_queued(
    authed: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down(run_id: uuid.UUID) -> str:
        raise OperationalError("broker down")

    monkeypatch.setattr(runs_api, "enqueue_run", down)
    show_id = await new_show(authed)

    response = await authed.post(f"/api/shows/{show_id}/runs")

    assert response.status_code == 503
    [run] = (await authed.get("/api/runs", params={"show_id": show_id})).json()
    assert run["status"] == "failed" and run["error"] == "The job queue is unavailable"
    # and the show is not blocked by it
    monkeypatch.setattr(runs_api, "enqueue_run", lambda run_id: "ok")
    assert (await authed.post(f"/api/shows/{show_id}/runs")).status_code == 202


# --- reading -----------------------------------------------------------------------------------


async def test_list_shows_newest_first_with_filters_and_paging(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User, broker: Spy
) -> None:
    a = await new_show(authed, "A")
    b = await new_show(authed, "B")
    now = datetime.now(UTC)
    rows = [
        Run(user_id=admin_user.id, show_id=uuid.UUID(a), trigger=RunTrigger.MANUAL,
            status=RunStatus.FAILED, created_at=now - timedelta(hours=3)),
        Run(user_id=admin_user.id, show_id=uuid.UUID(a), trigger=RunTrigger.SCHEDULE,
            status=RunStatus.SUCCEEDED, created_at=now - timedelta(hours=2)),
        Run(user_id=admin_user.id, show_id=uuid.UUID(b), trigger=RunTrigger.MANUAL,
            status=RunStatus.SUCCEEDED, created_at=now - timedelta(hours=1)),
    ]  # fmt: skip
    db_session.add_all(rows)
    await db_session.flush()

    everything = (await authed.get("/api/runs")).json()
    only_a = (await authed.get("/api/runs", params={"show_id": a})).json()
    failed = (await authed.get("/api/runs", params={"status": "failed"})).json()
    page = (await authed.get("/api/runs", params={"limit": 1, "offset": 1})).json()

    assert [r["id"] for r in everything] == [str(rows[2].id), str(rows[1].id), str(rows[0].id)]
    assert [r["id"] for r in only_a] == [str(rows[1].id), str(rows[0].id)]
    assert [r["id"] for r in failed] == [str(rows[0].id)]
    assert [r["id"] for r in page] == [str(rows[1].id)]
    assert all("events" not in r for r in everything)
    assert (await authed.get("/api/runs", params={"status": "bogus"})).status_code == 422
    assert (await authed.get("/api/runs", params={"limit": 0})).status_code == 422


async def test_runs_of_other_users_are_invisible(
    authed: AsyncClient, db_session: AsyncSession
) -> None:
    other = await make_user(db_session, "other@example.com")
    theirs = await make_show(db_session, other, slug="theirs")
    run = Run(user_id=other.id, show_id=theirs.id, trigger=RunTrigger.MANUAL)
    db_session.add(run)
    await db_session.flush()

    assert (await authed.get("/api/runs")).json() == []
    assert (await authed.get(f"/api/runs/{run.id}")).status_code == 404
    assert (await authed.post(f"/api/runs/{run.id}/cancel")).status_code == 404
    await db_session.refresh(run)
    assert run.status is RunStatus.QUEUED and not run.cancel_requested


async def test_the_detail_has_the_whole_log_in_order(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User, broker: Spy
) -> None:
    show_id = await new_show(authed)
    run_id = (await authed.post(f"/api/shows/{show_id}/runs")).json()["id"]
    run = await db_session.get(Run, uuid.UUID(run_id))
    assert run is not None
    await add_event(db_session, run, "Collected 3 items", stage="ingest", new_items=3)
    await add_event(db_session, run, "Source failed", level=EventLevel.WARNING, stage="ingest")
    await db_session.flush()

    detail = (await authed.get(f"/api/runs/{run_id}")).json()

    assert [(e["message"], e["level"], e["stage"]) for e in detail["events"]] == [
        ("Run queued", "info", None),
        ("Collected 3 items", "info", "ingest"),
        ("Source failed", "warning", "ingest"),
    ]
    assert detail["events"][1]["data"] == {"new_items": 3}
    assert detail["events"][0]["data"] == {"trigger": "manual"}


async def test_an_unknown_run_is_404(authed: AsyncClient) -> None:
    assert (await authed.get(f"/api/runs/{uuid.uuid4()}")).status_code == 404
    assert (await authed.get("/api/runs/not-a-uuid")).status_code == 422


# --- cancelling --------------------------------------------------------------------------------


async def test_cancelling_a_queued_run_ends_it_at_once_and_revokes_the_task(
    authed: AsyncClient, broker: Spy
) -> None:
    show_id = await new_show(authed)
    run = (await authed.post(f"/api/shows/{show_id}/runs")).json()

    response = await authed.post(f"/api/runs/{run['id']}/cancel")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled" and body["finished_at"] is not None
    assert body["cancel_requested"] is True
    assert [e["message"] for e in body["events"]][-1] == "Run cancelled before it started"
    assert broker.revoked == ["task-1"]
    # the show is free for a new run
    assert (await authed.post(f"/api/shows/{show_id}/runs")).status_code == 202


async def test_cancelling_a_running_run_asks_it_to_stop(
    authed: AsyncClient, db_session: AsyncSession, broker: Spy
) -> None:
    show_id = await new_show(authed)
    run_id = (await authed.post(f"/api/shows/{show_id}/runs")).json()["id"]
    await finish(db_session, run_id, RunStatus.RUNNING)

    body = (await authed.post(f"/api/runs/{run_id}/cancel")).json()

    assert body["status"] == "running" and body["cancel_requested"] is True
    assert body["events"][-1]["message"].startswith("Cancellation requested")
    row = (await db_session.scalars(select(Run).where(Run.id == uuid.UUID(run_id)))).one()
    assert row.cancel_requested


async def test_a_finished_run_cannot_be_cancelled(
    authed: AsyncClient, db_session: AsyncSession, broker: Spy
) -> None:
    show_id = await new_show(authed)
    run_id = (await authed.post(f"/api/shows/{show_id}/runs")).json()["id"]
    await finish(db_session, run_id, RunStatus.SUCCEEDED)

    response = await authed.post(f"/api/runs/{run_id}/cancel")

    assert response.status_code == 409 and "already ended" in response.json()["detail"]
    assert broker.revoked == []


async def test_requires_a_session(client: AsyncClient) -> None:
    some = uuid.uuid4()

    assert (await client.post(f"/api/shows/{some}/runs")).status_code == 401
    assert (await client.get("/api/runs")).status_code == 401
    assert (await client.get(f"/api/runs/{some}")).status_code == 401
    assert (await client.post(f"/api/runs/{some}/cancel")).status_code == 401
