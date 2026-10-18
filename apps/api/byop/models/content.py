import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
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
from byop.models.enums import EpisodeStatus, enum_type

if TYPE_CHECKING:
    from byop.models.show import Show


class Item(Base):
    """A story pulled from a source, de-duplicated per show by canonical URL."""

    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("show_id", "canonical_url"),
        Index("ix_items_show_id_content_hash", "show_id", "content_hash"),
        Index(
            "ix_items_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = id_column()
    user_id: Mapped[uuid.UUID] = user_id_column()
    show_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shows.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL"), index=True
    )
    canonical_url: Mapped[str] = mapped_column(String(2048))
    content_hash: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, server_default="", default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    language: Mapped[str | None] = mapped_column(String(16))
    rank_score: Mapped[float | None] = mapped_column(Float)
    used_in_episode_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("episodes.id", ondelete="SET NULL"), index=True
    )
    # Held for a run that has picked this item but not finished (an item belongs to at most one
    # run at a time); released if the run fails or its draft is rejected.
    reserved_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    show: Mapped["Show"] = relationship(back_populates="items")


class Episode(Base):
    __tablename__ = "episodes"

    id: Mapped[uuid.UUID] = id_column()
    user_id: Mapped[uuid.UUID] = user_id_column()
    show_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shows.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, server_default="", default="")
    # Structured multi-speaker script: [{speaker, text}, ...] plus metadata.
    script: Mapped[JsonObject | None] = mapped_column(JSONB)
    audio_key: Mapped[str | None] = mapped_column(String(500))
    duration_s: Mapped[int | None] = mapped_column(Integer)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[EpisodeStatus] = mapped_column(
        enum_type(EpisodeStatus, "episode_status"),
        server_default=EpisodeStatus.DRAFT.value,
        default=EpisodeStatus.DRAFT,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    show: Mapped["Show"] = relationship(back_populates="episodes")
