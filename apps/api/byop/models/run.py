import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from byop.models.base import Base
from byop.models.columns import created_at_column, id_column, updated_at_column, user_id_column
from byop.models.enums import RunStatus, RunTrigger, enum_type

if TYPE_CHECKING:
    from byop.models.show import Show


class Run(Base):
    """One generation attempt for a show, from ingest to a finished episode."""

    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint("progress BETWEEN 0 AND 100", name="progress_range"),
        Index("ix_runs_show_id_created_at", "show_id", "created_at"),
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
    celery_task_id: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    show: Mapped["Show"] = relationship(back_populates="runs")
