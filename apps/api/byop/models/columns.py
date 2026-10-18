"""Column helpers shared by every model."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

# JSON documents stored in JSONB columns.
type JsonObject = dict[str, object]


def id_column() -> Mapped[uuid.UUID]:
    return mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )


def created_at_column() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def updated_at_column() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


def user_id_column() -> Mapped[uuid.UUID]:
    """Owner of the row; deleting a user removes everything they own."""
    return mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
