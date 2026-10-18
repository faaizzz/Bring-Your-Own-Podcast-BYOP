import asyncio
import uuid

from byop.services.credentials import CredentialResolver
from byop.services.ingest.pipeline import ingest_show
from byop.tasks.runtime import task_deps
from byop.worker import celery_app


async def _run(show_id: uuid.UUID, run_id: uuid.UUID | None) -> dict[str, object]:
    async with task_deps() as (session, _redis, settings):
        result = await ingest_show(
            session, CredentialResolver(session, settings), settings, show_id, run_id=run_id
        )
    return result.as_dict()


@celery_app.task(name="byop.ingest_show")
def ingest_show_task(show_id: str, run_id: str | None = None) -> dict[str, object]:
    """Collect fresh items for a show; returns the counts (and per-source status) as JSON."""
    return asyncio.run(_run(uuid.UUID(show_id), uuid.UUID(run_id) if run_id else None))
