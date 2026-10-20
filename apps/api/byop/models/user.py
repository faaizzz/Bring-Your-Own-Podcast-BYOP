import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from byop.models.base import Base
from byop.models.columns import (
    created_at_column,
    id_column,
    updated_at_column,
    user_id_column,
)
from byop.models.enums import CredentialProvider, enum_type


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = id_column()
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class ProviderCredential(Base):
    """A user's override of an instance-wide provider key; the secret is stored encrypted."""

    __tablename__ = "provider_credentials"
    __table_args__ = (UniqueConstraint("user_id", "provider"),)

    id: Mapped[uuid.UUID] = id_column()
    user_id: Mapped[uuid.UUID] = user_id_column()
    provider: Mapped[CredentialProvider] = mapped_column(
        enum_type(CredentialProvider, "credential_provider")
    )
    # Fernet token of a JSON document (api_key, base_url, extra).
    secret_encrypted: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class UserSettings(Base):
    """Per-user defaults chosen in the app. One row per user, created on first save."""

    __tablename__ = "user_settings"

    id: Mapped[uuid.UUID] = id_column()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    # The model that searches the web for sources (a provider ref and a model id); both or neither.
    discovery_llm_provider: Mapped[str | None] = mapped_column(String(50), default=None)
    discovery_llm_model: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
