import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, String, Text, UniqueConstraint, false, text, true
from sqlalchemy.orm import Mapped, mapped_column

from byop.models.base import Base
from byop.models.columns import (
    created_at_column,
    id_column,
    updated_at_column,
    user_id_column,
)


class ProviderConnection(Base):
    """A user's own OpenAI-compatible endpoint (Ollama, vLLM, a gateway, a second Kokoro, ...).

    Shows and speakers point at it with the provider reference `conn:<id>`.
    """

    __tablename__ = "provider_connections"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[uuid.UUID] = id_column()
    user_id: Mapped[uuid.UUID] = user_id_column()
    name: Mapped[str] = mapped_column(String(60))
    base_url: Mapped[str] = mapped_column(String(2048))
    # Fernet token of a JSON document: {"api_key": str | null, "headers": [{name, value}]}.
    secret_encrypted: Mapped[str] = mapped_column(Text)
    # What the endpoint may be used for.
    llm: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    tts: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    web_search: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    # Seconds to wait between two requests to the server (0 = no wait), for low rate limits.
    min_interval_s: Mapped[float] = mapped_column(Float, server_default=text("0"), default=0.0)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
