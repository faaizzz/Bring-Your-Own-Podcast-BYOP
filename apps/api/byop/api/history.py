import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from byop.api.deps import CurrentUser, SessionDep
from byop.models.enums import RunStatus, RunTrigger
from byop.schemas.run import HistoryPage, HistoryRow
from byop.services import history as service

router = APIRouter(prefix="/history", tags=["history"])


def _duration_s(row: service.HistoryRow) -> int | None:
    run = row.run
    if run.started_at is None or run.finished_at is None:
        return None
    return max(0, round((run.finished_at - run.started_at).total_seconds()))


@router.get("", response_model=HistoryPage)
async def list_history(
    user: CurrentUser,
    session: SessionDep,
    show_id: uuid.UUID | None = None,
    run_status: Annotated[RunStatus | None, Query(alias="status")] = None,
    trigger: RunTrigger | None = None,
    created_from: Annotated[date | None, Query(description="First day (UTC), inclusive")] = None,
    created_to: Annotated[date | None, Query(description="Last day (UTC), inclusive")] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=service.MAX_LIMIT)] = 50,
) -> HistoryPage:
    """Runs of all shows (or one), newest first, with their episode and cost.

    Page through with `next_cursor`: pass it back as `cursor` until it is `null`.
    """
    filters = service.HistoryFilters(
        show_id=show_id,
        status=run_status,
        trigger=trigger,
        created_from=created_from,
        created_to=created_to,
    )
    try:
        page = await service.list_history(session, user.id, filters, cursor=cursor, limit=limit)
    except service.InvalidCursor as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return HistoryPage(
        items=[
            HistoryRow(
                id=row.run.id,
                show_id=row.run.show_id,
                show_title=row.show_title,
                trigger=row.run.trigger,
                status=row.run.status,
                stage=row.run.stage,
                progress=row.run.progress,
                error=row.run.error,
                created_at=row.run.created_at,
                started_at=row.run.started_at,
                finished_at=row.run.finished_at,
                duration_s=_duration_s(row),
                cost_usd=row.cost_usd,
                episode_id=row.episode_id,
                episode_title=row.episode_title,
                episode_status=row.episode_status,
            )
            for row in page.rows
        ],
        next_cursor=page.next_cursor,
    )
