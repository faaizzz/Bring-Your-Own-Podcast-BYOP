from celery import Celery

from byop.config import get_settings

settings = get_settings()

celery_app = Celery(
    "byop",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Periodic jobs are registered here by the scheduler story.
    beat_schedule={},
)


@celery_app.task(name="byop.ping")
def ping() -> str:
    """Round-trip check for the worker, broker and result backend."""
    return "pong"
