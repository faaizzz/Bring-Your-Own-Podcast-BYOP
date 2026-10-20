"""Designing a style or a persona from a sentence, with a language model.

Nothing is saved: the draft goes back to the person, who edits it in the usual form and saves it
there. The call is an ordinary billed one: it is recorded as usage with `stage="assist"` (no show,
no run), so it appears on the Costs page, and traced in Langfuse when that is set up.
"""

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings
from byop.models.enums import ShowStyle
from byop.providers.llm import (
    CallMetadata,
    LLMError,
    LLMResponseError,
    Message,
    UnsupportedLLMProvider,
    get_llm,
)
from byop.schemas.assist import AssistRequest, PersonaDraft, StyleDraft
from byop.services.credentials import (
    CredentialDecryptionError,
    CredentialResolver,
    ProviderNotConfigured,
)
from byop.services.discovery_errors import explain_llm_error, explain_unexpected
from byop.services.langfuse import open_assist_tracer
from byop.services.llm_choice import instance_model
from byop.services.provider_ref import ProviderRef
from byop.services.script_writer import LANGUAGE_NAMES, TEMPLATES, language_base
from byop.services.styles import StyleInvalid, builtin_instructions, check_instructions
from byop.services.usage import capture_usage
from byop.services.web_search import PROVIDER_LABELS

log = structlog.get_logger(__name__)

STAGE = "assist"
TEMPERATURE = 0.8
SYSTEM_PROMPT = (
    "You are an experienced podcast producer. You answer with the JSON object that was asked for."
)
# Shows the shape and level of detail of good instructions; the style it is written in is not the
# point, so the same one is always used.
EXAMPLE_STYLE = ShowStyle.CONVERSATIONAL


class AssistUnavailable(Exception):
    """Nothing can be designed yet (no model chosen or set up); the message says what to do."""


class AssistFailed(Exception):
    """The model could not make a usable draft; the message says why."""


def _language_name(language: str | None) -> str:
    if not language:
        return "English"
    return LANGUAGE_NAMES.get(language_base(language), language)


def _choose(settings: Settings, request: AssistRequest) -> tuple[ProviderRef, str]:
    if request.provider and request.model:
        return ProviderRef.parse(request.provider), request.model
    chosen = instance_model(settings)
    if chosen is None:
        raise AssistUnavailable(
            "No language model is set up for this. Choose a model in the dialog, or set "
            "DEFAULT_LLM_PROVIDER and DEFAULT_LLM_MODEL in .env."
        )
    return chosen


async def _draft[T: (StyleDraft, PersonaDraft)](
    session: AsyncSession,
    resolver: CredentialResolver,
    settings: Settings,
    user_id: uuid.UUID,
    request: AssistRequest,
    *,
    kind: str,
    template: str,
    schema: type[T],
    **template_values: object,
) -> T:
    provider, model = _choose(settings, request)
    try:
        config = await resolver.get_ref(user_id, provider, "llm")
        llm = get_llm(config.provider, config)
    except (ProviderNotConfigured, CredentialDecryptionError, UnsupportedLLMProvider) as exc:
        raise AssistUnavailable(
            f"The {provider} provider is not set up: {exc}. Configure it under "
            "Settings › Integrations, or choose another model."
        ) from exc
    label = config.label or PROVIDER_LABELS.get(config.provider, config.provider.value)

    prompt = TEMPLATES.get_template(template).render(
        brief=request.brief,
        language_name=_language_name(request.language),
        **template_values,
    )
    tracer = await open_assist_tracer(session, resolver, user_id, kind)
    await tracer.start()
    outcome, message = "ok", None
    try:
        async with capture_usage(session, user_id, listener=tracer.record):
            result = await llm.complete(
                [Message("system", SYSTEM_PROMPT), Message("user", prompt)],
                model=model,
                response_schema=schema,
                temperature=TEMPERATURE,
                metadata=CallMetadata(stage=STAGE, tags={"kind": kind}),
            )
    except LLMResponseError as exc:
        outcome, message = "failed", str(exc)
        raise AssistFailed(
            f"{label} did not return a usable {kind} draft, even after asking again. Try again, "
            "or choose another model."
        ) from exc
    except LLMError as exc:
        outcome, message = "failed", str(exc)
        raise AssistFailed(explain_llm_error(exc, provider=label, model=model)) from exc
    except Exception as exc:
        outcome, message = "failed", str(exc)
        log.exception("assist_failed", kind=kind)
        raise AssistFailed(explain_unexpected(exc)) from exc
    finally:
        await llm.aclose()
        await tracer.finish(outcome, message, last=True)
    assert isinstance(result.parsed, schema)
    return result.parsed


async def design_style(
    session: AsyncSession,
    resolver: CredentialResolver,
    settings: Settings,
    user_id: uuid.UUID,
    request: AssistRequest,
) -> StyleDraft:
    draft = await _draft(
        session,
        resolver,
        settings,
        user_id,
        request,
        kind="style",
        template="assist_style.md",
        schema=StyleDraft,
        example=builtin_instructions(EXAMPLE_STYLE).strip(),
    )
    try:
        check_instructions(draft.instructions)  # what is saved later must render
    except StyleInvalid as exc:
        raise AssistFailed(
            f"The model wrote instructions that cannot be used ({exc}). Try again."
        ) from exc
    return draft


async def design_persona(
    session: AsyncSession,
    resolver: CredentialResolver,
    settings: Settings,
    user_id: uuid.UUID,
    request: AssistRequest,
) -> PersonaDraft:
    return await _draft(
        session,
        resolver,
        settings,
        user_id,
        request,
        kind="persona",
        template="assist_persona.md",
        schema=PersonaDraft,
    )
