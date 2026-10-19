"""Whether a model can search the web, which source discovery needs.

The answer is `yes`, `no` or `unknown`, and a `no` carries a message that says what to change.
"""

import enum
import uuid
from dataclasses import dataclass

import structlog
from redis.asyncio import Redis

from byop.models.enums import CredentialProvider
from byop.providers.llm import ModelInfo, UnsupportedLLMProvider, get_llm
from byop.services.credentials import (
    CredentialDecryptionError,
    CredentialResolver,
    ProviderConfig,
    ProviderNotConfigured,
)
from byop.services.models import list_models_cached
from byop.services.provider_ref import ProviderRef

log = structlog.get_logger(__name__)

ONLINE_SUFFIX = ":online"
# OpenAI's chat models that search the web themselves.
OPENAI_SEARCH_MARKER = "search"

PROVIDER_LABELS = {
    CredentialProvider.OPENROUTER: "OpenRouter",
    CredentialProvider.OPENAI: "OpenAI",
}

HOW_TO_FIX = (
    "Choose a model that can search the web for this show (on OpenRouter, any text model works "
    "through the ':online' plugin and 'perplexity/sonar' searches natively), or set "
    "DISCOVERY_LLM_PROVIDER and DISCOVERY_LLM_MODEL in .env to a model that can."
)


class WebSearch(enum.StrEnum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SearchCheck:
    support: WebSearch
    provider_label: str
    # For `no`: why, and what to do. For `unknown`: the caveat to show with the results.
    message: str | None = None


def _label(ref: ProviderRef, config: ProviderConfig | None) -> str:
    if config is not None and config.label:
        return config.label
    return PROVIDER_LABELS.get(ref.builtin, str(ref)) if ref.builtin else str(ref)


def _no(label: str, model: str, why: str, fix: str = HOW_TO_FIX) -> str:
    return f"The model '{model}' on {label} cannot search the web: {why} {fix}"


async def _openrouter(
    resolver: CredentialResolver,
    redis: Redis,
    config: ProviderConfig,
    model: str,
    label: str,
) -> SearchCheck:
    if model.endswith(ONLINE_SUFFIX) or model.startswith("perplexity/"):
        return SearchCheck(WebSearch.YES, label)
    try:
        llm = get_llm(config.provider, config)
        try:
            models = await list_models_cached(redis, llm, config)
        finally:
            await llm.aclose()
    except Exception as exc:  # a provider outage must not block discovery
        log.warning("web_search_check_unavailable", provider="openrouter", error=type(exc).__name__)
        return SearchCheck(
            WebSearch.UNKNOWN, label, f"Could not check whether '{model}' can search the web."
        )
    info: ModelInfo | None = next((m for m in models if m.id == model), None)
    if info is None:
        if not models:
            return SearchCheck(
                WebSearch.UNKNOWN, label, f"Could not check whether '{model}' can search the web."
            )
        return SearchCheck(
            WebSearch.NO, label, _no(label, model, f"{label} does not offer a model with that id.")
        )
    if info.output_modalities and "text" not in info.output_modalities:
        return SearchCheck(
            WebSearch.NO,
            label,
            _no(label, model, "it does not produce text, which is what we ask for."),
        )
    return SearchCheck(WebSearch.YES, label)  # natively, or through the `:online` plugin


async def check_web_search(
    resolver: CredentialResolver,
    redis: Redis,
    user_id: uuid.UUID,
    ref: ProviderRef,
    model: str,
) -> SearchCheck:
    """Can `model` on `ref` search the web? A provider that is not set up is `unknown`: that is
    reported on its own, not as a missing capability."""
    try:
        config = await resolver.get_ref(user_id, ref, "llm")
    except (ProviderNotConfigured, CredentialDecryptionError, UnsupportedLLMProvider):
        return SearchCheck(WebSearch.UNKNOWN, _label(ref, None))
    label = _label(ref, config)

    if ref.is_connection:
        if config.web_search:
            return SearchCheck(WebSearch.YES, label)
        return SearchCheck(
            WebSearch.NO,
            label,
            _no(
                label,
                model,
                f"the connection '{label}' is not marked as able to search the web.",
                "If the server's models can search, turn on 'Web search' for the connection under "
                "Settings › Integrations; otherwise choose a model that can, or set "
                "DISCOVERY_LLM_PROVIDER and DISCOVERY_LLM_MODEL in .env.",
            ),
        )
    if ref.builtin is CredentialProvider.OPENROUTER:
        return await _openrouter(resolver, redis, config, model, label)
    if ref.builtin is CredentialProvider.OPENAI:
        if OPENAI_SEARCH_MARKER in model:
            return SearchCheck(WebSearch.YES, label)
        return SearchCheck(
            WebSearch.NO,
            label,
            _no(
                label,
                model,
                "only OpenAI's search models (such as gpt-4o-search-preview) do.",
                "Choose one of them, or a model on OpenRouter, for this show, or set "
                "DISCOVERY_LLM_PROVIDER and DISCOVERY_LLM_MODEL in .env.",
            ),
        )
    return SearchCheck(
        WebSearch.UNKNOWN, label, f"Could not confirm that '{model}' on {label} can search the web."
    )
