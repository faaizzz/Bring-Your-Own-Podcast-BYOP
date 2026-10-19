import pytest

from byop.providers.llm import LLMError
from byop.services.discovery_errors import explain_llm_error, explain_unexpected


def error(status: int | None, detail: str | None = None, code: str | None = None) -> LLMError:
    return LLMError("x", status_code=status, detail=detail, code=code)


def explain(exc: LLMError) -> str:
    return explain_llm_error(exc, provider="OpenRouter", model="vendor/model")


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (error(401, "bad key"), "rejected the API key"),
        (error(403), "rejected the API key"),
        (error(402, "payment required"), "cannot pay for this request"),
        (error(400, "Insufficient credits"), "cannot pay for this request"),
        (error(429, "slow down"), "rate limiting requests for 'vendor/model'"),
        (error(404, "No endpoints found for vendor/model"), "does not know the model"),
        (error(400, "model not found"), "does not know the model"),
        # A model id that merely contains "online" is a bad id, not a search problem.
        (error(400, "vendor/x:online is not a valid model ID"), "does not know the model"),
        (
            error(400, "the web plugin is not supported by this model"),
            "refused the web-search request",
        ),
        (error(422, "unsupported tool web_search"), "refused the web-search request"),
        (
            error(400, "something else entirely"),
            "rejected the request for 'vendor/model' (HTTP 400)",
        ),
        (error(500, "boom"), "rejected the request for 'vendor/model' (HTTP 500)"),
    ],
)
def test_known_provider_failures_get_an_actionable_message(exc: LLMError, expected: str) -> None:
    message = explain(exc)

    assert expected in message
    assert "OpenRouter" in message


def test_the_providers_own_words_are_always_included() -> None:
    message = explain(error(400, "context length exceeded"))

    assert "The provider said: context length exceeded" in message


def test_a_failure_without_a_status_falls_back_to_the_error_text() -> None:
    assert "Could not reach openrouter" in explain(LLMError("Could not reach openrouter"))


def test_an_unexpected_failure_names_its_kind_and_reason() -> None:
    message = explain_unexpected(RuntimeError("kaboom"))

    assert "RuntimeError: kaboom" in message and "worker log" in message
    assert "ValueError" in explain_unexpected(ValueError())
