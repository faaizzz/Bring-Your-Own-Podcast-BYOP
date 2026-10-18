"""Everything the landing page shows, gathered in a handful of queries."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Episode, Run, Show, UsageEvent
from byop.models.enums import EpisodeStatus, RunStatus, ScheduleKind
from byop.providers.llm import LLM_PROVIDERS
from byop.schemas.dashboard import (
    ActiveRun,
    Dashboard,
    LatestEpisode,
    Onboarding,
    RecentFailure,
    UpcomingRun,
)
from byop.services.credentials import CredentialResolver, ProviderNotConfigured

UPCOMING_DAYS = 7
SUCCESS_WINDOW_DAYS = 30
FAILURE_WINDOW_DAYS = 7
LIST_LIMIT = 5
ACTIVE = (RunStatus.QUEUED, RunStatus.RUNNING)
MADE_AN_EPISODE = (RunStatus.SUCCEEDED, RunStatus.AWAITING_REVIEW)


def month_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _count(session: AsyncSession, *conditions: object) -> int:
    return int(await session.scalar(select(func.count()).where(*conditions)) or 0)  # type: ignore[arg-type]


async def provider_configured(resolver: CredentialResolver, user_id: uuid.UUID) -> bool:
    """Whether at least one language-model provider has credentials (from the user or `.env`)."""
    for provider in LLM_PROVIDERS:
        try:
            await resolver.get(user_id, provider)
        except ProviderNotConfigured:
            continue
        return True
    return False


async def _recent_failures(
    session: AsyncSession, user_id: uuid.UUID, now: datetime, busy: set[uuid.UUID]
) -> list[RecentFailure]:
    """Shows whose newest run failed in the last week. A later run, whatever its outcome,
    replaces the failure, so the list only holds what still needs attention."""
    newest_rows = await session.execute(
        select(Run.show_id, func.max(Run.created_at))
        .where(Run.user_id == user_id)
        .group_by(Run.show_id)
    )
    newest = dict(newest_rows.all())
    rows = await session.execute(
        select(Run, Show.title)
        .join(Show, Show.id == Run.show_id)
        .where(
            Run.user_id == user_id,
            Run.status == RunStatus.FAILED,
            Run.created_at >= now - timedelta(days=FAILURE_WINDOW_DAYS),
        )
        .order_by(Run.created_at.desc())
    )
    return [
        RecentFailure(
            run_id=run.id,
            show_id=run.show_id,
            show_title=title,
            error=run.error,
            stage=run.stage,
            finished_at=run.finished_at,
            can_retry=run.show_id not in busy,
        )
        for run, title in rows
        if newest.get(run.show_id) == run.created_at
    ][:LIST_LIMIT]


async def build_dashboard(
    session: AsyncSession,
    resolver: CredentialResolver,
    user_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> Dashboard:
    now = now or datetime.now(UTC)
    since = month_start(now)

    shows = await _count(session, Show.user_id == user_id)
    episodes = await _count(session, Episode.user_id == user_id)
    spend = await session.scalar(
        select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(
            UsageEvent.user_id == user_id, UsageEvent.created_at >= since
        )
    )

    ended = await session.execute(
        select(Run.status, func.count())
        .where(
            Run.user_id == user_id,
            Run.created_at >= now - timedelta(days=SUCCESS_WINDOW_DAYS),
            Run.status.in_((*MADE_AN_EPISODE, RunStatus.FAILED)),
        )
        .group_by(Run.status)
    )
    counts = {status: int(n) for status, n in ended}
    finished = sum(counts.values())
    succeeded = sum(counts.get(status, 0) for status in MADE_AN_EPISODE)

    upcoming = await session.execute(
        select(Show.id, Show.title, Show.next_run_at)
        .where(
            Show.user_id == user_id,
            Show.schedule_kind != ScheduleKind.MANUAL,
            Show.paused.is_(False),
            Show.next_run_at.is_not(None),
            Show.next_run_at <= now + timedelta(days=UPCOMING_DAYS),
        )
        .order_by(Show.next_run_at)
    )
    active_rows = await session.execute(
        select(Run, Show.title)
        .join(Show, Show.id == Run.show_id)
        .where(Run.user_id == user_id, Run.status.in_(ACTIVE))
        .order_by(Run.created_at)
    )
    active = [
        ActiveRun(
            id=run.id,
            show_id=run.show_id,
            show_title=title,
            status=run.status,
            stage=run.stage,
            progress=run.progress,
            started_at=run.started_at,
        )
        for run, title in active_rows
    ]

    latest_rows = await session.execute(
        select(Episode, Show.title)
        .join(Show, Show.id == Episode.show_id)
        .where(Episode.user_id == user_id)
        .order_by(func.coalesce(Episode.published_at, Episode.created_at).desc(), Episode.id)
        .limit(LIST_LIMIT)
    )
    latest = [
        LatestEpisode(
            id=episode.id,
            show_id=episode.show_id,
            show_title=title,
            title=episode.title,
            status=episode.status,
            created_at=episode.created_at,
            published_at=episode.published_at,
            duration_s=episode.duration_s,
            audio_url=(
                f"/api/episodes/{episode.id}/audio?v={int(episode.updated_at.timestamp())}"
                if episode.audio_key
                else None
            ),
        )
        for episode, title in latest_rows
    ]

    return Dashboard(
        shows=shows,
        episodes_this_month=await _count(
            session, Episode.user_id == user_id, Episode.created_at >= since
        ),
        spend_this_month_usd=Decimal(str(spend or 0)),
        success_rate=(succeeded / finished) if finished else None,
        finished_runs_30d=finished,
        drafts_to_review=await _count(
            session, Episode.user_id == user_id, Episode.status == EpisodeStatus.DRAFT
        ),
        upcoming=[
            UpcomingRun(show_id=show_id, show_title=title, next_run_at=at)
            for show_id, title, at in upcoming
            if at is not None
        ],
        active_runs=active,
        recent_failures=await _recent_failures(session, user_id, now, {a.show_id for a in active}),
        latest_episodes=latest,
        onboarding=Onboarding(
            provider_configured=await provider_configured(resolver, user_id),
            show_created=shows > 0,
            episode_generated=episodes > 0,
        ),
    )
