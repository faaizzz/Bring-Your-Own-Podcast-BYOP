from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, SecretStr, model_validator

from byop.models.enums import CredentialProvider


class IntegrationUpdate(BaseModel):
    """Create or update the user's override. Omitted fields keep their stored value."""

    api_key: SecretStr | None = Field(default=None, max_length=2048)
    base_url: HttpUrl | None = None
    extra: dict[str, str] | None = None
    enabled: bool = True
    # Seconds to wait between two requests to the provider (0 = no wait). Sent alone, it changes
    # nothing else, so a key that comes from `.env` stays where it is.
    min_interval_s: float | None = Field(default=None, ge=0, le=60)

    @model_validator(mode="after")
    def _limit_extra(self) -> "IntegrationUpdate":
        if self.extra is not None and len(self.extra) > 10:
            raise ValueError("extra may hold at most 10 entries")
        return self


class IntegrationResponse(BaseModel):
    """Never contains a secret: keys and extras are masked."""

    provider: CredentialProvider
    source: Literal["user", "env", "none"]
    enabled: bool
    api_key_masked: str | None = None
    base_url: str | None = None
    extra_masked: dict[str, str] = Field(default_factory=dict)
    problem: str | None = None
    min_interval_s: float = 0


class IntegrationTestResponse(BaseModel):
    ok: bool
    detail: str
