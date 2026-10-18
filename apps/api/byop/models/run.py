import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from byop.models.base import Base
from byop.models.columns import (
    JsonObject,
    created_at_column,
    id_column,
    updated_at_column,
    user_id_column,
)
from byop.models.enums import EventLevel, RunStatus, RunTrigger, enum_type

if TYPE_CHECKING:
    from byop.models.show import Show


class Run(Base):
    """One generation attempt for a show, from ingest to a finished episode."""

    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint("progress BETWEEN 0 AND 100", name="progress_range"),
        Index("ix_runs_show_id_created_at", "show_id", "created_at"),
        # At most one run per show may be waiting or working at any time.
        Index(
            "uq_runs_one_active_per_show",
            "show_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = id_column()
    user_id: Mapped[uuid.UUID] = user_id_column()
    show_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shows.id", ondelete="CASCADE"), index=True
    )
    trigger: Mapped[RunTrigger] = mapped_column(enum_type(RunTrigger, "run_trigger"))
    status: Mapped[RunStatus] = mapped_column(
        enum_type(RunStatus, "run_status"),
        server_default=RunStatus.QUEUED.value,
        default=RunStatus.QUEUED,
        index=True,
    )
    stage: Mapped[str | None] = mapped_column(String(50))
    progress: Mapped[int] = mapped_column(SmallInteger, server_default="0", default=0)
    error: Mapped[str | None] = mapped_column(Text)
    # Set by the cancel endpoint; stages look at it between steps and stop.
    cancel_requested: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    show: Mapped["Show"] = relationship(back_populates="runs")
    events: Mapped[list["RunEvent"]] = relationship(
        back_populates="run",
        order_by="RunEvent.ts, RunEvent.id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class RunEvent(Base):
    """One line of a run's log: what a stage did, warned about or failed on."""

    __tablename__ = "run_events"
    __table_args__ = (Index("ix_run_events_run_id_ts", "run_id", "ts"),)

    id: Mapped[uuid.UUID] = id_column()
    user_id: Mapped[uuid.UUID] = user_id_column()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    level: Mapped[EventLevel] = mapped_column(
        enum_type(EventLevel, "event_level"),
        server_default=EventLevel.INFO.value,
        default=EventLevel.INFO,
    )
    stage: Mapped[str | None] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[JsonObject | None] = mapped_column(JSONB)

    run: Mapped[Run] = relationship(back_populates="events")
