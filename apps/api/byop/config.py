from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from byop.models.enums import ShowStyle


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
    # Where media (covers, audio) lives: the local volume, or any S3-compatible service.
    storage_backend: Literal["local", "s3"] = "local"
    s3_endpoint_url: str | None = None  # empty for AWS; e.g. http://s3:9000 for the minio profile
    # Address handed to browsers in links when the server is not reachable under its endpoint.
    s3_public_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None

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

    # Sources are fetched from user-supplied URLs. By default only public internet addresses are
    # allowed; set this to reach feeds on your own network (e.g. a self-hosted RSS bridge).
    sources_allow_private_networks: bool = False

    # Runs (the generation pipeline).
    run_timeout_minutes: int = Field(default=60, ge=1)  # no progress for this long: failed
    run_stage_max_retries: int = Field(default=3, ge=0)  # for transient errors, per stage
    run_reaper_interval_s: int = Field(default=60, ge=5)  # how often stuck runs are looked for

    # Text-to-speech stage.
    tts_concurrency: int = Field(default=4, ge=1, le=16)  # chunks synthesized at once
    tts_chunk_retries: int = Field(default=2, ge=0)  # extra attempts per chunk before the fallback
    tts_retry_backoff_s: float = Field(default=1.0, ge=0)  # doubles with each retry

    # Ingest (collecting stories for an episode).
    ingest_freshness_days: int = Field(default=3, ge=1)  # older items are not collected
    ingest_dedup_days: int = Field(default=14, ge=1)  # titles are compared against this window
    ingest_title_similarity: float = Field(default=0.55, gt=0, le=1)  # pg_trgm threshold
    ingest_source_timeout_s: float = Field(default=30.0, gt=0)

    # Discovery asks a model with web search for sources. Unset: the show's model, then the
    # instance default. On OpenRouter ":online" is appended so the model can search the web.
    discovery_llm_provider: Literal["openrouter", "openai", "openai_compatible"] | None = None
    discovery_llm_model: str | None = None

    # Defaults for new shows (a show can override each of them).
    default_llm_provider: Literal["openrouter", "openai", "openai_compatible"] | None = None
    default_llm_model: str | None = None
    default_show_style: ShowStyle = ShowStyle.NEWS_BRIEFING

    log_level: str = "INFO"

    @field_validator(
        "default_llm_provider",
        "default_llm_model",
        "discovery_llm_provider",
        "discovery_llm_model",
        "s3_endpoint_url",
        "s3_public_endpoint_url",
        "s3_bucket",
        "s3_access_key_id",
        "s3_secret_access_key",
        mode="before",
    )
    @classmethod
    def _blank_means_unset(cls, value: object) -> object:
        """`DEFAULT_LLM_MODEL=` in .env is an empty string, which should fall back to unset."""
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("s3_region", mode="before")
    @classmethod
    def _blank_region_is_default(cls, value: object) -> object:
        return "us-east-1" if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _s3_needs_its_settings(self) -> Self:
        if self.storage_backend == "s3":
            missing = [
                name.upper()
                for name in ("s3_bucket", "s3_access_key_id", "s3_secret_access_key")
                if not getattr(self, name)
            ]
            if missing:
                raise ValueError(f"STORAGE_BACKEND=s3 needs {', '.join(missing)}")
        return self

    @field_validator("default_show_style", mode="before")
    @classmethod
    def _blank_style_is_default(cls, value: object) -> object:
        return ShowStyle.NEWS_BRIEFING if isinstance(value, str) and not value.strip() else value

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
