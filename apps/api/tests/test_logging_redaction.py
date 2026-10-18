import json

import pytest
import structlog
from pydantic import SecretStr

from byop.logging import REDACTED, configure_logging


def logged(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]


@pytest.fixture(autouse=True)
def _configure() -> None:
    configure_logging("INFO")


def test_sensitive_keys_and_secretstr_are_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    structlog.get_logger("t").info(
        "call",
        api_key="sk-real-key-123456",
        password="hunter2",
        wrapped=SecretStr("shh"),
        headers={"Authorization": "Bearer abc.def.ghi", "Accept": "json"},
        provider="openai",
    )

    (line,) = logged(capsys)
    assert line["api_key"] == line["password"] == line["wrapped"] == REDACTED
    assert line["headers"] == {"Authorization": REDACTED, "Accept": "json"}
    assert line["provider"] == "openai"


def test_secret_looking_values_in_messages_are_scrubbed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    structlog.get_logger("t").warning(
        "failed with sk-or-v1-abcdef0123456789 and Authorization: Bearer abc123.def", url="x"
    )

    (line,) = logged(capsys)
    assert "abcdef0123456789" not in str(line["event"])
    assert "abc123" not in str(line["event"])


def test_tracebacks_are_scrubbed(capsys: pytest.CaptureFixture[str]) -> None:
    try:
        raise RuntimeError("upstream rejected Bearer topsecret-token-value")
    except RuntimeError:
        structlog.get_logger("t").exception("boom")

    (line,) = logged(capsys)
    assert "topsecret-token-value" not in json.dumps(line)


def test_token_counts_are_not_mistaken_for_secrets(capsys: pytest.CaptureFixture[str]) -> None:
    structlog.get_logger("t").info("usage", input_tokens=120, output_tokens=40)

    (line,) = logged(capsys)
    assert (line["input_tokens"], line["output_tokens"]) == (120, 40)


def test_stdlib_records_are_scrubbed_too(capsys: pytest.CaptureFixture[str]) -> None:
    import logging

    logging.getLogger("uvicorn.error").error("oops key sk-abcdefgh12345678")

    (line,) = logged(capsys)
    assert "abcdefgh12345678" not in json.dumps(line)
