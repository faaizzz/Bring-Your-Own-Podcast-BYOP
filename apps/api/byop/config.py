from functools import lru_cache
from typing import Self

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """Raised when the environment does not describe a valid configuration."""


class Settings(BaseSettings):
    """Application settings, read from the environment (and `.env` for local runs)."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        extra="ignore",
    )

    # Core
    byop_secret_key: SecretStr = Field(min_length=16)
    byop_admin_email: str = "admin@example.com"
    byop_admin_password: SecretStr | None = None
    public_base_url: str = "http://localhost:8080"
    # How long a login session (JWT cookie) stays valid.
    byop_session_hours: int = Field(default=168, ge=1)
    media_root: str = "/data/media"

    # Infrastructure
    database_url: str = "postgresql+asyncpg://byop:byop@localhost:5432/byop"
    redis_url: str = "redis://localhost:6379/0"

    # Provider keys (optional; may also be stored encrypted via Settings > Integrations)
    openrouter_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    elevenlabs_api_key: SecretStr | None = None
    # Local Kokoro text-to-speech (OpenAI-compatible), e.g. http://kokoro:8880/v1
    kokoro_base_url: str | None = None

    # Langfuse tracing (optional)
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    log_level: str = "INFO"

    @classmethod
    def load(cls) -> Self:
        """Build settings, turning validation errors into one readable message."""
        try:
            return cls()  # type: ignore[call-arg]  # required values come from the environment
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in err['loc']).upper()}: {err['msg']}"
                for err in exc.errors()
            )
            hint = ""
            if any(err["loc"] == ("byop_secret_key",) for err in exc.errors()):
                hint = " Set BYOP_SECRET_KEY (at least 16 characters), e.g. `openssl rand -hex 32`."
            raise ConfigError(f"Invalid configuration - {problems}.{hint}") from exc


@lru_cache
def get_settings() -> Settings:
    return Settings.load()
