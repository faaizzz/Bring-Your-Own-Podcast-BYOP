import uuid
from datetime import datetime

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from byop.models.base import Base
from byop.models.columns import (
    created_at_column,
    id_column,
    updated_at_column,
    user_id_column,
)


class Style(Base):
    """A show style of the user's own. The built-in ones are templates in the code, not rows."""

    __tablename__ = "styles"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[uuid.UUID] = id_column()
    user_id: Mapped[uuid.UUID] = user_id_column()
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, server_default="", default="")
    # Markdown for the script writer: how the episode is built and sounds. May use the prompt
    # placeholders (see `services/styles.py`).
    instructions: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
