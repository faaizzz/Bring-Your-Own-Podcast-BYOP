from celery import Celery

from byop.config import get_settings

settings = get_settings()

celery_app = Celery(
    "byop",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["byop.tasks.discovery", "byop.tasks.ingest", "byop.tasks.pipeline"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Periodic jobs. The scheduler story adds the per-show schedules here.
    beat_schedule={
        "reap-stuck-runs": {
            "task": "byop.reap_runs",
            "schedule": float(settings.run_reaper_interval_s),
        },
    },
)


@celery_app.task(name="byop.ping")
def ping() -> str:
    """Round-trip check for the worker, broker and result backend."""
    return "pong"
