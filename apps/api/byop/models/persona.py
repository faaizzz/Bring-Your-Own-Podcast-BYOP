import uuid
from datetime import datetime

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from byop.models.base import Base
from byop.models.columns import (
    JsonObject,
    created_at_column,
    id_column,
    updated_at_column,
    user_id_column,
)


class Persona(Base):
    """A speaker persona kept in the user's library, with an optional default voice.

    Applying one to a speaker copies its text (and voice): speakers never point back at it, so
    editing or deleting a persona changes nothing about the shows that used it.
    """

    __tablename__ = "personas"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[uuid.UUID] = id_column()
    user_id: Mapped[uuid.UUID] = user_id_column()
    name: Mapped[str] = mapped_column(String(100))
    persona: Mapped[str] = mapped_column(Text)
    # The default voice: a provider and a voice together, or neither.
    tts_provider: Mapped[str | None] = mapped_column(String(50))
    voice_id: Mapped[str | None] = mapped_column(String(200))
    voice_params: Mapped[JsonObject] = mapped_column(JSONB, server_default="{}", default=dict)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
