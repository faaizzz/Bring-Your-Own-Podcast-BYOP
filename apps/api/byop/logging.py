import logging
import re
import sys
import uuid
from collections.abc import Awaitable, Callable
from typing import TextIO

import structlog
from fastapi import FastAPI, Request, Response
from pydantic import SecretBytes, SecretStr
from structlog.contextvars import bind_contextvars, clear_contextvars

REQUEST_ID_HEADER = "X-Request-ID"

_log = structlog.get_logger("byop.request")


REDACTED = "[redacted]"

# Keys whose values are never logged. `input_tokens`/`max_tokens` (counts) are not matched.
_SENSITIVE_KEY = re.compile(
    r"api[_-]?key|secret|passw(or)?d|authorization|cookie|credential|(^|[_-])token$", re.IGNORECASE
)
# Secret-looking values that slip into messages, URLs or tracebacks.
_SECRET_VALUE = re.compile(
    r"\bsk-[A-Za-z0-9_\-]{8,}|\bBearer\s+[A-Za-z0-9._~+/\-]+=*|\bxi-[A-Za-z0-9]{8,}",
    re.IGNORECASE,
)


class _StdoutHandler(logging.StreamHandler[TextIO]):
    """Writes to whatever `sys.stdout` is at emit time (survives redirects and test capture)."""

    def __init__(self) -> None:
        logging.Handler.__init__(self)

    @property
    def stream(self) -> TextIO:  # type: ignore[override]  # read-only on purpose
        return sys.stdout


def _redact(value: object, key: str | None = None) -> object:
    if isinstance(value, SecretStr | SecretBytes):
        return REDACTED
    if key is not None and value is not None and _SENSITIVE_KEY.search(key):
        return REDACTED
    if isinstance(value, dict):
        return {k: _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _SECRET_VALUE.sub(REDACTED, value)
    return value


def redact_secrets(
    _logger: object, _method: str, event_dict: structlog.typing.EventDict
) -> structlog.typing.EventDict:
    """structlog processor: scrub secrets from every event before it is rendered."""
    return {k: _redact(v, k) for k, v in event_dict.items()}


def configure_logging(level: str = "INFO") -> None:
    """Emit JSON logs for both structlog and stdlib (uvicorn, celery) records."""
    shared: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    structlog.configure(
        processors=[
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    handler = _StdoutHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,  # render tracebacks so they get scrubbed too
                redact_secrets,
                structlog.processors.JSONRenderer(),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Their per-request INFO lines add noise and echo URLs.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def install_request_logging(app: FastAPI) -> None:
    """Bind a request id to every log line of a request and echo it in the response."""

    @app.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        clear_contextvars()
        bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        except Exception:
            _log.exception("request_failed", method=request.method, path=request.url.path)
            raise
        response.headers[REQUEST_ID_HEADER] = request_id
        _log.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
        )
        return response
