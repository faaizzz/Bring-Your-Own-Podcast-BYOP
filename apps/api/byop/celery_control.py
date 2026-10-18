import structlog
from kombu.exceptions import OperationalError

from byop.worker import celery_app

log = structlog.get_logger(__name__)


def revoke_quietly(task_id: str | None) -> None:
    """Tell workers to drop a task that has not started. Best effort: cancelling a run does
    not depend on it (stages stop at their next checkpoint either way)."""
    if not task_id:
        return
    try:
        celery_app.control.revoke(task_id)
    except OperationalError:
        log.warning("revoke_failed", task_id=task_id)
