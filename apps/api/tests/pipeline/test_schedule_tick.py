from datetime import UTC, datetime, time, timedelta

from kombu.exceptions import OperationalError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Run, User
from byop.models.enums import RunStatus, RunTrigger, ScheduleKind
from byop.tasks.schedule import tick
from byop.worker import celery_app
from tests.models.factories import make_show


async def due_show(session: AsyncSession, user: User) -> None:
    show = await make_show(session, user)
    show.schedule_kind, show.schedule_time = ScheduleKind.DAILY, time(9)
    show.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
    await session.flush()


async def test_the_tick_queues_the_pipeline_for_a_due_show(
    db_session: AsyncSession, admin_user: User
) -> None:
    await due_show(db_session, admin_user)
    enqueued: list[object] = []

    def enqueue(run_id: object) -> str:
        enqueued.append(run_id)
        return "task-1"

    assert await tick(db_session, None, enqueue) == 1

    run = (await db_session.scalars(select(Run))).one()
    assert enqueued == [run.id]
    assert run.trigger is RunTrigger.SCHEDULE and run.celery_task_id == "task-1"
    assert run.status is RunStatus.QUEUED
    assert await tick(db_session, None, enqueue) == 0  # nothing is due any more


async def test_a_broken_queue_fails_the_run_instead_of_leaving_it_queued(
    db_session: AsyncSession, admin_user: User
) -> None:
    await due_show(db_session, admin_user)

    def down(run_id: object) -> str:
        raise OperationalError("broker is down")

    assert await tick(db_session, None, down) == 0

    run = (await db_session.scalars(select(Run))).one()
    assert run.status is RunStatus.FAILED and run.error == "The job queue is unavailable"


def test_the_tick_is_scheduled_by_beat_every_minute() -> None:
    entry = celery_app.conf.beat_schedule["schedule-tick"]

    assert entry["task"] == "byop.schedule_tick"
    assert entry["schedule"] == 60.0
    assert "byop.tasks.schedule" in celery_app.conf.include
