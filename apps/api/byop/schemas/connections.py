import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, HttpUrl, SecretStr, StringConstraints, model_validator

# RFC 9110 header field names; the ones below are set by the HTTP stack and cannot be overridden.
_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]{1,64}$")
FORBIDDEN_HEADERS = frozenset({"host", "content-length", "transfer-encoding", "connection"})
MAX_HEADERS = 10

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
# Seconds to wait between two requests; see `services/throttle.py`.
MinInterval = Annotated[float, Field(ge=0, le=60)]


class HeaderIn(BaseModel):
    name: str
    # Omitted on an update keeps the stored value of the header with this name.
    value: SecretStr | None = Field(default=None, max_length=4096)

    @model_validator(mode="after")
    def _check_name(self) -> "HeaderIn":
        if not _HEADER_NAME.fullmatch(self.name):
            raise ValueError("header names use letters, digits and - _ . only (at most 64)")
        if self.name.lower() in FORBIDDEN_HEADERS:
            raise ValueError(f"the {self.name} header is set by BYOP and cannot be overridden")
        return self


def _check_headers(headers: list[HeaderIn]) -> None:
    names = [h.name.lower() for h in headers]
    if len(set(names)) != len(names):
        raise ValueError("a header name may appear only once")


class ConnectionCreate(BaseModel):
    name: Name
    base_url: HttpUrl
    api_key: SecretStr | None = Field(default=None, max_length=2048)
    headers: list[HeaderIn] = Field(default_factory=list, max_length=MAX_HEADERS)
    llm: bool = True
    tts: bool = False
    web_search: bool = False
    enabled: bool = True
    min_interval_s: MinInterval = 0

    @model_validator(mode="after")
    def _check(self) -> "ConnectionCreate":
        _check_headers(self.headers)
        if any(h.value is None for h in self.headers):
            raise ValueError("every header needs a value")
        if not (self.llm or self.tts or self.web_search):
            raise ValueError("enable at least one use: language models, voices or web search")
        return self


class ConnectionUpdate(BaseModel):
    """Omitted fields keep their value. `api_key` set to an empty string removes the key;
    `headers`, when given, replaces the whole list."""

    name: Name | None = None
    base_url: HttpUrl | None = None
    api_key: SecretStr | None = Field(default=None, max_length=2048)
    headers: list[HeaderIn] | None = Field(default=None, max_length=MAX_HEADERS)
    llm: bool | None = None
    tts: bool | None = None
    web_search: bool | None = None
    enabled: bool | None = None
    min_interval_s: MinInterval | None = None

    @model_validator(mode="after")
    def _check(self) -> "ConnectionUpdate":
        if self.headers is not None:
            _check_headers(self.headers)
        return self


class HeaderOut(BaseModel):
    name: str
    value_masked: str


class ConnectionResponse(BaseModel):
    """Never contains a secret: the key and the header values are masked."""

    id: uuid.UUID
    name: str
    base_url: str
    api_key_masked: str | None
    headers: list[HeaderOut]
    llm: bool
    tts: bool
    web_search: bool
    enabled: bool
    # Seconds to wait between two requests to the server (0 = no wait).
    min_interval_s: float
    # How many shows / speakers refer to the connection (it cannot be deleted while > 0).
    shows_using: int
    speakers_using: int
    problem: str | None = None
    created_at: datetime
    updated_at: datetime


class ConnectionCheck(BaseModel):
    capability: Literal["llm", "tts", "web_search"]
    ok: bool
    detail: str


class ConnectionTestResponse(BaseModel):
    ok: bool
    detail: str
    checks: list[ConnectionCheck]
