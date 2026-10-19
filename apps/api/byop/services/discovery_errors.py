"""Plain-language reasons for a failed discovery, from what the provider itself said."""

from byop.providers.llm import LLMError

# Words in a provider's message that say the model cannot use a web-search plugin or tool.
_NO_SEARCH = ("plugin", "web_search", "web search", "tool")
_NO_CREDITS = ("credit", "balance", "quota", "billing", "payment")
_NO_MODEL = (
    "not found",
    "no endpoints",
    "does not exist",
    "unknown model",
    "no such model",
    "not a valid model",
    "invalid model",
)


def _said(exc: LLMError) -> str:
    return f" The provider said: {exc.detail}" if exc.detail else ""


def explain_llm_error(exc: LLMError, *, provider: str, model: str) -> str:
    """What went wrong and what to do about it, never just "failed"."""
    text = f"{exc.detail or ''} {exc.code or ''}".lower()
    status = exc.status_code

    if status in (401, 403):
        return (
            f"{provider} rejected the API key. Check it under Settings › Integrations.{_said(exc)}"
        )
    if status == 402 or any(word in text for word in _NO_CREDITS):
        return (
            f"{provider} says the account cannot pay for this request (credits or quota used "
            f"up). Add credit with {provider}, or choose another model.{_said(exc)}"
        )
    if status == 429:
        return (
            f"{provider} is rate limiting requests for '{model}'. Wait a minute and try again, "
            f"or choose another model.{_said(exc)}"
        )
    if status == 404 or any(word in text for word in _NO_MODEL):
        return (
            f"{provider} does not know the model '{model}' (or has no provider serving it right "
            f"now). Choose another model.{_said(exc)}"
        )
    if status in (400, 422) and any(word in text for word in _NO_SEARCH):
        return (
            f"'{model}' on {provider} refused the web-search request, so it cannot be used for "
            "discovery. Choose a model that can search the web (on OpenRouter, "
            f"'perplexity/sonar' or any text model through ':online').{_said(exc)}"
        )
    if status is not None:
        return f"{provider} rejected the request for '{model}' (HTTP {status}).{_said(exc)}"
    return f"The language model failed: {exc}"


def explain_unexpected(exc: Exception) -> str:
    """For a bug or an odd failure: say what kind, so the report is useful."""
    reason = str(exc).strip()
    shown = f"{type(exc).__name__}: {reason[:200]}" if reason else type(exc).__name__
    return f"Discovery failed unexpectedly ({shown}). The worker log has the details."
