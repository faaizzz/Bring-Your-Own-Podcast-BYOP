"""Text-to-speech provider interface.

Everything that differs between providers (limits, wire formats, accepted parameters,
timeouts) is declared once in each provider's `ProviderQuirks`; no other code branches on
the provider.
"""

import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import ClassVar, Literal

import anyio
import httpx
import structlog
from tenacity import AsyncRetrying, RetryCallState, retry_if_exception, stop_after_attempt

from byop.providers.common import (
    CallMetadata,
    RetryPolicy,
    Throttle,
    UsageRecord,
    backoff_seconds,
    record_usage,
)
from byop.providers.tts.audio import CANONICAL_SAMPLE_RATE, AudioFormat, to_canonical_wav
from byop.providers.tts.errors import TTSError, TTSParamError

log = structlog.get_logger(__name__)

CANONICAL_FORMAT = "wav"


class _StatusError(Exception):
    def __init__(self, status_code: int, retry_after: str | None) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code
        self.retry_after = retry_after


@dataclass(frozen=True)
class Voice:
    id: str
    name: str
    language: str | None = None
    gender: str | None = None
    preview_url: str | None = None


@dataclass(frozen=True)
class SpeechModel:
    """A speech model a provider offers, for the "Voice model" picker."""

    id: str
    name: str
    description: str | None = None
    # The voices this model offers, when the provider says (OpenRouter does).
    voices: tuple[str, ...] = ()


@dataclass(frozen=True)
class TTSResult:
    audio_path: Path
    format: str
    sample_rate: int
    characters: int
    # Providers do not report cost; the usage story fills it from a price table.
    cost_usd: Decimal | None
    latency_ms: int


@dataclass(frozen=True)
class ParamSpec:
    """Type and bounds of one voice parameter."""

    kind: Literal["number", "integer", "string", "boolean"]
    minimum: float | None = None
    maximum: float | None = None
    max_length: int = 500  # strings only

    def problem(self, value: object) -> str | None:
        """Why `value` is not acceptable, or None."""
        if self.kind == "boolean":
            return None if isinstance(value, bool) else "must be true or false"
        if self.kind == "string":
            if not isinstance(value, str) or not value.strip():
                return "must be a non-empty string"
            if len(value) > self.max_length:
                return f"must be at most {self.max_length} characters"
            return None
        is_number = isinstance(value, int | float) and not isinstance(value, bool)
        if not is_number or (self.kind == "integer" and not isinstance(value, int)):
            return "must be a whole number" if self.kind == "integer" else "must be a number"
        number = float(value)  # type: ignore[arg-type]  # narrowed to int | float above
        if self.minimum is not None and number < self.minimum:
            return f"must be at least {self.minimum:g}"
        if self.maximum is not None and number > self.maximum:
            return f"must be at most {self.maximum:g}"
        return None


@dataclass(frozen=True)
class ProviderQuirks:
    max_chars_per_request: int
    # What the API can return, by our format name ("pcm", "mp3"), and which one we ask for.
    formats: Mapping[str, AudioFormat]
    default_format: str
    # Keys accepted in `params` (the speaker's voice parameters), besides `format`.
    supported_params: frozenset[str]
    required_params: frozenset[str] = frozenset()
    timeout_s: float = 120.0
    # Types and bounds for `supported_params`; a parameter without a spec is not checked.
    param_specs: Mapping[str, ParamSpec] = field(default_factory=dict)
    # The voice parameter that names the speech model ("model", "model_id"); None when the
    # provider has no choice of model. The web shows it as a "Voice model" list.
    model_param: str | None = None
    # Whether the list of voices depends on the chosen model (OpenRouter's does).
    voices_follow_model: bool = False
    # How many requests may run at once against this provider; None means no limit of its own.
    # For servers that work through requests one at a time (a local model on a CPU).
    max_concurrency: int | None = None

    def value_problems(self, params: Mapping[str, object]) -> dict[str, str]:
        """Parameter name -> why its value is unacceptable (supported parameters only)."""
        problems: dict[str, str] = {}
        for key, value in params.items():
            spec = self.param_specs.get(key)
            if spec is not None and (message := spec.problem(value)):
                problems[key] = message
        return problems


@dataclass(frozen=True)
class AudioRequest:
    """One HTTP request that returns audio."""

    url: str
    json: dict[str, object]
    headers: dict[str, str] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, _StatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return isinstance(exc, httpx.TransportError)  # includes timeouts


class TTSProvider(ABC):
    name: str
    quirks: ClassVar[ProviderQuirks]
    # The speech model used when a speaker names none; None when the caller must choose.
    default_model: ClassVar[str | None] = None
    # Spaces out the requests when the user set a wait for this provider (see `get_tts`).
    throttle: Throttle | None = None

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_s: float | None = None,
        retry: RetryPolicy | None = None,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._retry = retry or RetryPolicy()
        self._http = httpx.AsyncClient(
            timeout=timeout_s or self.quirks.timeout_s, headers=default_headers
        )

    @property
    def max_chars_per_request(self) -> int:
        return self.quirks.max_chars_per_request

    # -- provider-specific parts ------------------------------------------------------------

    @abstractmethod
    def build_request(
        self, text: str, voice_id: str, params: Mapping[str, object], audio_format: AudioFormat
    ) -> AudioRequest:
        """The HTTP request that synthesizes `text` in `audio_format`."""

    @abstractmethod
    async def list_voices(self, model: str | None = None) -> list[Voice]:
        """The voices this provider offers (those of `model` when voices depend on it)."""

    async def list_models(self) -> list[SpeechModel]:
        """The speech models to choose from; empty when the provider has no list of them (the
        caller then lets the user type a model id)."""
        return []

    # -- shared flow ------------------------------------------------------------------------

    def _validate(self, text: str, params: Mapping[str, object]) -> AudioFormat:
        quirks = self.quirks
        if not text.strip():
            raise TTSParamError("There is no text to synthesize")
        if len(text) > quirks.max_chars_per_request:
            raise TTSParamError(
                f"Text is {len(text)} characters; {self.name} accepts at most "
                f"{quirks.max_chars_per_request} per request"
            )
        unknown = set(params) - quirks.supported_params - {"format"}
        if unknown:
            raise TTSParamError(
                f"{self.name} does not support parameter(s): {', '.join(sorted(unknown))}"
            )
        missing = quirks.required_params - set(params)
        if missing:
            raise TTSParamError(f"{self.name} requires parameter(s): {', '.join(sorted(missing))}")
        if problems := quirks.value_problems(params):
            key, message = next(iter(sorted(problems.items())))
            raise TTSParamError(f"{self.name} parameter '{key}' {message}")
        format_name = str(params.get("format", quirks.default_format))
        if format_name not in quirks.formats:
            raise TTSParamError(
                f"{self.name} cannot produce '{format_name}' "
                f"(available: {', '.join(sorted(quirks.formats))})"
            )
        return quirks.formats[format_name]

    def _wait(self, state: RetryCallState) -> float:
        exc = state.outcome.exception() if state.outcome else None
        retry_after = exc.retry_after if isinstance(exc, _StatusError) else None
        return backoff_seconds(self._retry, state.attempt_number, retry_after)

    def _retrying(self) -> AsyncRetrying:
        return AsyncRetrying(
            stop=stop_after_attempt(self._retry.max_attempts),
            wait=self._wait,
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        )

    def _translate(self, exc: Exception) -> TTSError:
        if isinstance(exc, _StatusError):
            return TTSError(
                f"{self.name} request failed (HTTP {exc.status_code})", status_code=exc.status_code
            )
        if isinstance(exc, httpx.TimeoutException):
            return TTSError(f"{self.name} request timed out")
        return TTSError(f"Could not reach {self.name}")

    async def _download(self, request: AudioRequest, destination: Path) -> None:
        """Stream the audio response to `destination` (never buffering a whole file)."""

        async def attempt() -> None:
            if self.throttle is not None:
                await self.throttle.wait()  # every try, including a retry after a 429
            async with self._http.stream(
                "POST",
                request.url,
                json=request.json,
                headers=request.headers,
                params=request.query,
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise _StatusError(response.status_code, response.headers.get("retry-after"))
                async with await anyio.open_file(destination, "wb") as out:
                    async for chunk in response.aiter_bytes():
                        await out.write(chunk)

        try:
            await self._retrying()(attempt)
        except (_StatusError, httpx.HTTPError) as exc:
            raise self._translate(exc) from exc

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str,
        output_dir: Path,
        params: Mapping[str, object] | None = None,
        metadata: CallMetadata | None = None,
    ) -> TTSResult:
        """Synthesize `text` into a canonical WAV (24 kHz, mono, 16-bit) inside `output_dir`."""
        started = time.perf_counter()
        started_at = datetime.now(UTC)
        params = params or {}
        audio_format = self._validate(text, params)
        request = self.build_request(text, voice_id, params, audio_format)

        await anyio.Path(output_dir).mkdir(parents=True, exist_ok=True)
        stem = uuid.uuid4().hex
        raw = output_dir / f"{stem}.{audio_format.extension}.part"
        wav = output_dir / f"{stem}.{CANONICAL_FORMAT}"
        try:
            await self._download(request, raw)
            if (await anyio.Path(raw).stat()).st_size == 0:
                raise TTSError(f"{self.name} returned no audio")
            await to_canonical_wav(raw, audio_format, wav)
        except BaseException:
            await anyio.Path(wav).unlink(missing_ok=True)
            raise
        finally:
            await anyio.Path(raw).unlink(missing_ok=True)

        latency_ms = int((time.perf_counter() - started) * 1000)
        meta = metadata or CallMetadata()
        log.info(
            "tts_synthesize",
            provider=self.name,
            stage=meta.stage,
            run_id=str(meta.run_id) if meta.run_id else None,
            show_id=str(meta.show_id) if meta.show_id else None,
            characters=len(text),
            format=audio_format.name,
            latency_ms=latency_ms,
        )
        model = params.get("model")
        record_usage(
            UsageRecord(
                kind="tts",
                provider=self.name,
                model=model if isinstance(model, str) else None,
                stage=meta.stage,
                run_id=meta.run_id,
                show_id=meta.show_id,
                latency_ms=latency_ms,
                characters=len(text),
                started_at=started_at,
                tags={**meta.tags, "voice": voice_id},
            )
        )
        return TTSResult(
            audio_path=wav,
            format=CANONICAL_FORMAT,
            sample_rate=CANONICAL_SAMPLE_RATE,
            characters=len(text),
            cost_usd=None,
            latency_ms=latency_ms,
        )

    async def _get_json(self, url: str, headers: Mapping[str, str]) -> object:
        async def attempt() -> object:
            response = await self._http.get(url, headers=dict(headers))
            if response.status_code >= 400:
                raise _StatusError(response.status_code, response.headers.get("retry-after"))
            return response.json()

        try:
            return await self._retrying()(attempt)
        except (_StatusError, httpx.HTTPError) as exc:
            raise self._translate(exc) from exc

    async def aclose(self) -> None:
        await self._http.aclose()
