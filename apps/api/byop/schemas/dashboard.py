import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from byop.models.enums import EpisodeStatus, RunStatus


class UpcomingRun(BaseModel):
    show_id: uuid.UUID
    show_title: str
    next_run_at: datetime


class ActiveRun(BaseModel):
    id: uuid.UUID
    show_id: uuid.UUID
    show_title: str
    status: RunStatus
    stage: str | None
    progress: int
    started_at: datetime | None


class RecentFailure(BaseModel):
    run_id: uuid.UUID
    show_id: uuid.UUID
    show_title: str
    error: str | None
    stage: str | None
    finished_at: datetime | None
    # The show can be run again right now (nothing is queued or running for it).
    can_retry: bool


class LatestEpisode(BaseModel):
    id: uuid.UUID
    show_id: uuid.UUID
    show_title: str
    title: str
    status: EpisodeStatus
    created_at: datetime
    published_at: datetime | None
    duration_s: int | None
    audio_url: str | None


class Onboarding(BaseModel):
    """The first-run checklist; each step is done when its condition holds."""

    provider_configured: bool
    show_created: bool
    episode_generated: bool


class Dashboard(BaseModel):
    shows: int
    episodes_this_month: int
    spend_this_month_usd: Decimal
    # Share of the runs that ended in the last 30 days and made an episode; None before any ended.
    success_rate: float | None
    finished_runs_30d: int
    drafts_to_review: int
    upcoming: list[UpcomingRun]
    active_runs: list[ActiveRun]
    recent_failures: list[RecentFailure]
    latest_episodes: list[LatestEpisode]
    onboarding: Onboarding
