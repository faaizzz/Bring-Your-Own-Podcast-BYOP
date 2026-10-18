import uuid
from typing import Any

import pytest
from celery.exceptions import Retry

from byop.config import get_settings
from byop.pipeline.errors import TransientStageError
from byop.pipeline.orchestrator import STAGES
from byop.tasks import pipeline as tasks
from byop.worker import celery_app


def test_the_chain_runs_every_stage_in_order_with_no_result_passing() -> None:
    run_id = uuid.uuid4()

    chain = tasks.build_chain(run_id)

    assert [t.task for t in chain.tasks] == ["byop.run_stage"] * len(STAGES)
    assert [t.args for t in chain.tasks] == [(str(run_id), s.name) for s in STAGES]
    assert all(t.immutable for t in chain.tasks)  # a stage never receives the previous result


def test_enqueue_returns_the_id_of_the_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    class Result:
        id = "last-task-id"

    monkeypatch.setattr("celery.canvas._chain.apply_async", lambda self, *a, **k: Result())

    assert tasks.enqueue_run(uuid.uuid4()) == "last-task-id"


def test_the_reaper_is_scheduled_by_beat() -> None:
    entry = celery_app.conf.beat_schedule["reap-stuck-runs"]

    assert entry["task"] == "byop.reap_runs"
    assert entry["schedule"] == float(get_settings().run_reaper_interval_s)
    assert "byop.tasks.pipeline" in celery_app.conf.include


class FakeRetry(Exception):
    pass


def call(
    monkeypatch: pytest.MonkeyPatch,
    *,
    retries: int,
    fail_with: Exception | None,
    max_retries: int = 3,
) -> tuple[Any, dict[str, Any]]:
    """Run the stage task body with the async parts stubbed out; returns (result, spy)."""
    spy: dict[str, Any] = {"gave_up": None, "retry": None}

    async def fake_run_stage(run_id: uuid.UUID, stage: str, task_id: str | None) -> str:
        if fail_with is not None:
            raise fail_with
        return "done"

    async def fake_give_up(run_id: uuid.UUID, stage: str, message: str) -> None:
        spy["gave_up"] = (stage, message)

    def fake_retry(**kwargs: Any) -> None:
        spy["retry"] = kwargs
        raise FakeRetry

    monkeypatch.setattr(tasks, "_run_stage", fake_run_stage)
    monkeypatch.setattr(tasks, "_give_up", fake_give_up)
    monkeypatch.setattr(tasks.run_stage_task, "retry", fake_retry)
    monkeypatch.setenv("RUN_STAGE_MAX_RETRIES", str(max_retries))
    get_settings.cache_clear()
    tasks.run_stage_task.push_request(retries=retries)
    try:
        try:
            result: Any = tasks.run_stage_task.run(str(uuid.uuid4()), "tts")
        except FakeRetry:
            result = "retrying"
    finally:
        tasks.run_stage_task.pop_request()
        get_settings.cache_clear()
    return result, spy


def test_a_stage_that_succeeds_returns_its_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    result, spy = call(monkeypatch, retries=0, fail_with=None)

    assert result == "done" and spy == {"gave_up": None, "retry": None}


@pytest.mark.parametrize(("retries", "delay"), [(0, 5), (1, 10), (2, 20), (3, 40)])
def test_transient_errors_are_retried_with_growing_delays(
    monkeypatch: pytest.MonkeyPatch, retries: int, delay: int
) -> None:
    result, spy = call(
        monkeypatch, retries=retries, fail_with=TransientStageError("503"), max_retries=10
    )

    assert result == "retrying"
    assert spy["retry"]["countdown"] == delay and spy["retry"]["max_retries"] == 10
    assert spy["gave_up"] is None


def test_the_retry_delay_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    _, spy = call(monkeypatch, retries=9, fail_with=TransientStageError("x"), max_retries=20)

    assert spy["retry"]["countdown"] == tasks.MAX_RETRY_DELAY_S


def test_after_the_last_retry_the_run_is_failed_not_retried_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, spy = call(monkeypatch, retries=3, fail_with=TransientStageError("503"), max_retries=3)

    assert result == "failed" and spy["retry"] is None
    assert spy["gave_up"] == ("tts", "tts kept failing after 3 retries: 503")


def test_the_retry_exception_is_celerys(monkeypatch: pytest.MonkeyPatch) -> None:
    assert issubclass(Retry, Exception)  # the real task re-raises Celery's Retry from self.retry
