import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from byop.models.base import Base
from byop.models.columns import created_at_column, id_column, updated_at_column, user_id_column
from byop.models.enums import CostSource, UsageKind, enum_type


class UsageEvent(Base):
    """One billable LLM or TTS call.

    Unlike other show-owned rows, usage survives the deletion of its show or run
    (the references are nulled) so cost history stays accurate.
    """

    __tablename__ = "usage_events"
    __table_args__ = (Index("ix_usage_events_user_id_created_at", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = id_column()
    user_id: Mapped[uuid.UUID] = user_id_column()
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), index=True
    )
    show_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shows.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[UsageKind] = mapped_column(enum_type(UsageKind, "usage_kind"))
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(200))
    stage: Mapped[str | None] = mapped_column(String(50))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    characters: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), server_default="0", default=Decimal("0")
    )
    cost_source: Mapped[CostSource] = mapped_column(
        enum_type(CostSource, "cost_source"),
        server_default=CostSource.UNKNOWN.value,
        default=CostSource.UNKNOWN,
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
