import uuid
from datetime import datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    false,
    true,
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
from byop.models.content import Episode, Item
from byop.models.enums import ScheduleKind, ShowStyle, SourceKind, SourceOrigin, enum_type
from byop.models.run import Run


class Show(Base):
    __tablename__ = "shows"
    __table_args__ = (
        CheckConstraint("target_minutes > 0", name="target_minutes_positive"),
        CheckConstraint("items_per_episode > 0", name="items_per_episode_positive"),
        CheckConstraint(
            "schedule_weekday IS NULL OR schedule_weekday BETWEEN 0 AND 6",
            name="schedule_weekday_range",
        ),
        CheckConstraint(
            "schedule_monthday IS NULL OR schedule_monthday BETWEEN 1 AND 31",
            name="schedule_monthday_range",
        ),
    )

    id: Mapped[uuid.UUID] = id_column()
    user_id: Mapped[uuid.UUID] = user_id_column()
    title: Mapped[str] = mapped_column(String(200))
    # Public identifier used in feed URLs, so it is unique across the instance.
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    topic: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default="", default="")
    language: Mapped[str] = mapped_column(String(16), server_default="en", default="en")
    target_minutes: Mapped[int] = mapped_column(Integer, server_default="10", default=10)
    style: Mapped[ShowStyle] = mapped_column(
        enum_type(ShowStyle, "show_style"),
        server_default=ShowStyle.NEWS_BRIEFING.value,
        default=ShowStyle.NEWS_BRIEFING,
    )
    prompt_override: Mapped[str | None] = mapped_column(Text)
    # Free-text guidance for choosing stories, e.g. "prefer releases over funding news".
    ranking_hints: Mapped[str | None] = mapped_column(Text)
    llm_provider: Mapped[str | None] = mapped_column(String(50))
    llm_model: Mapped[str | None] = mapped_column(String(200))
    items_per_episode: Mapped[int] = mapped_column(Integer, server_default="5", default=5)

    schedule_kind: Mapped[ScheduleKind] = mapped_column(
        enum_type(ScheduleKind, "schedule_kind"),
        server_default=ScheduleKind.MANUAL.value,
        default=ScheduleKind.MANUAL,
    )
    schedule_time: Mapped[time | None] = mapped_column(Time)
    schedule_weekday: Mapped[int | None] = mapped_column(SmallInteger)
    schedule_monthday: Mapped[int | None] = mapped_column(SmallInteger)
    timezone: Mapped[str] = mapped_column(String(64), server_default="UTC", default="UTC")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    paused: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    auto_publish: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)

    feed_author: Mapped[str | None] = mapped_column(String(200))
    feed_email: Mapped[str | None] = mapped_column(String(320))
    feed_category: Mapped[str | None] = mapped_column(String(100))
    feed_explicit: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    cover_key: Mapped[str | None] = mapped_column(String(500))
    # Optional audio branding, stored under the show's prefix: a clip before and after the
    # speech, and a music bed that plays (ducked) under it.
    intro_key: Mapped[str | None] = mapped_column(String(500))
    outro_key: Mapped[str | None] = mapped_column(String(500))
    music_key: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    # Children are removed by the database (ON DELETE CASCADE); the ORM must not load them first.
    speakers: Mapped[list["Speaker"]] = relationship(
        back_populates="show",
        order_by="Speaker.position",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    sources: Mapped[list["Source"]] = relationship(
        back_populates="show", cascade="all, delete-orphan", passive_deletes=True
    )
    items: Mapped[list[Item]] = relationship(
        back_populates="show", cascade="all, delete-orphan", passive_deletes=True
    )
    runs: Mapped[list[Run]] = relationship(
        back_populates="show", cascade="all, delete-orphan", passive_deletes=True
    )
    episodes: Mapped[list[Episode]] = relationship(
        back_populates="show", cascade="all, delete-orphan", passive_deletes=True
    )


class Speaker(Base):
    __tablename__ = "speakers"
    __table_args__ = (UniqueConstraint("show_id", "position"),)

    id: Mapped[uuid.UUID] = id_column()
    user_id: Mapped[uuid.UUID] = user_id_column()
    show_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shows.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(100))
    persona: Mapped[str] = mapped_column(Text, server_default="", default="")
    tts_provider: Mapped[str] = mapped_column(String(50))
    voice_id: Mapped[str] = mapped_column(String(200))
    voice_params: Mapped[JsonObject] = mapped_column(JSONB, server_default="{}", default=dict)
    fallback_tts_provider: Mapped[str | None] = mapped_column(String(50))
    fallback_voice_id: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    show: Mapped[Show] = relationship(back_populates="speakers")


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("show_id", "kind", "value"),)

    id: Mapped[uuid.UUID] = id_column()
    user_id: Mapped[uuid.UUID] = user_id_column()
    show_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shows.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[SourceKind] = mapped_column(enum_type(SourceKind, "source_kind"))
    # Feed URL, page URL or search query, depending on `kind`.
    value: Mapped[str] = mapped_column(String(2048))
    name: Mapped[str | None] = mapped_column(String(200))
    origin: Mapped[SourceOrigin] = mapped_column(
        enum_type(SourceOrigin, "source_origin"),
        server_default=SourceOrigin.USER.value,
        default=SourceOrigin.USER,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    show: Mapped[Show] = relationship(back_populates="sources")
