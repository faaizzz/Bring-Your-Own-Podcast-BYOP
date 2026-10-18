from fastapi import APIRouter

from byop.api.deps import CurrentUser, SessionDep
from byop.api.integrations import ResolverDep
from byop.schemas.dashboard import Dashboard
from byop.services.dashboard import build_dashboard

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=Dashboard)
async def dashboard(user: CurrentUser, session: SessionDep, resolver: ResolverDep) -> Dashboard:
    """Everything the home page shows in one call: totals, what is running, what is scheduled,
    what failed, the latest episodes and the first-run checklist."""
    return await build_dashboard(session, resolver, user.id)
