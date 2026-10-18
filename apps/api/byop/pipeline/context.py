import uuid
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings
from byop.models import Run, RunEvent, Show
from byop.models.enums import EventLevel, RunStatus
from byop.pipeline.errors import RunStopped
from byop.services.credentials import CredentialResolver
from byop.services.run_stream import announce
from byop.services.usage import flush_current


@dataclass
class RunContext:
    """What a stage gets: the run, its show and the services it needs.

    Stages talk to the outside world only through this object, which is also how a run's
    log, progress and cancellation work.
    """

    session: AsyncSession
    settings: Settings
    resolver: CredentialResolver
    run: Run
    show: Show
    stage: str
    progress_start: int
    progress_end: int
    redis: Redis | None = None  # to tell open run streams that something changed

    @property
    def user_id(self) -> uuid.UUID:
        return self.run.user_id

    async def log(
        self, message: str, *, level: EventLevel = EventLevel.INFO, **data: object
    ) -> None:
        """Append a line to the run's log (visible while the run is still going)."""
        self.session.add(
            RunEvent(
                user_id=self.run.user_id,
                run_id=self.run.id,
                level=level,
                stage=self.stage,
                message=message,
                data=dict(data) or None,
            )
        )
        await self.session.commit()
        await flush_current(self.session, self.user_id)
        await announce(self.redis, self.run.id)

    async def progress(self, fraction: float) -> None:
        """Report how far through this stage the work is (0.0 to 1.0).

        Also the run's heartbeat: a run whose row has not changed for `RUN_TIMEOUT_MINUTES`
        is considered stuck, so stages that take long must call this regularly.
        """
        span = self.progress_end - self.progress_start
        self.run.progress = self.progress_start + round(span * min(1.0, max(0.0, fraction)))
        self.run.updated_at = func.now()
        await self.session.commit()
        await flush_current(self.session, self.user_id)  # spend shows up while a stage works
        await announce(self.redis, self.run.id)

    async def checkpoint(self) -> None:
        """Stop with `RunStopped` if the run was cancelled or ended; call between steps."""
        await self.session.refresh(self.run, ["status", "cancel_requested"])
        if self.run.cancel_requested or self.run.status not in (
            RunStatus.QUEUED,
            RunStatus.RUNNING,
        ):
            raise RunStopped
