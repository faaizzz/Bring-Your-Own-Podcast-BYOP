"""The persona library: reusable speaker personas, with an optional default voice.

A persona is copied into a speaker when it is applied (the web does that), never linked, so the
library can change freely. Every user starts with a few starter personas, which are theirs to
edit or delete.
"""

import uuid
from collections.abc import Mapping

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Persona
from byop.providers.tts import voice_param_problems
from byop.schemas.personas import PersonaIn, PersonaUpdate
from byop.services.provider_ref import ProviderRef
from byop.services.validation import FieldError, FieldValidationError, param_errors

# Offered to every new user, and added to existing users by migration 0015.
STARTER_PERSONAS: tuple[tuple[str, str], ...] = (
    (
        "Curious host",
        "The curious lead host. Warm and well prepared; introduces each story, explains why it "
        "matters and asks the questions a listener would ask.",
    ),
    (
        "Expert analyst",
        "The expert. Calm and precise; brings background, numbers and context, separates what is "
        "known from what is guessed, and explains without jargon.",
    ),
    (
        "Friendly sceptic",
        "The friendly sceptic. Good-humoured but hard to impress; asks for evidence, points out "
        "hype and plays devil's advocate without being unkind.",
    ),
    (
        "Storyteller",
        "The storyteller. Paints a picture, uses analogies and small anecdotes, and builds each "
        "story so that the listener wants to know what happens next.",
    ),
    (
        "Plain-language explainer",
        "The explainer. Turns technical news into plain language with simple examples, and checks "
        "that nothing important was lost on the way.",
    ),
)


class PersonaNotFound(Exception):
    pass


class PersonaConflict(Exception):
    """The name is taken."""


async def seed_starter_personas(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Give the user the starter personas they do not have yet. Safe to repeat: it never makes
    a duplicate (nor brings back one that was deleted, because nothing calls it again)."""
    await session.execute(
        insert(Persona)
        .values([{"user_id": user_id, "name": n, "persona": p} for n, p in STARTER_PERSONAS])
        .on_conflict_do_nothing(index_elements=["user_id", "name"])
    )


def _voice_errors(provider: str | None, params: Mapping[str, object]) -> list[FieldError]:
    if provider is None:
        return []
    return param_errors(
        ("body", "voice_params"), voice_param_problems(ProviderRef.parse(provider).kind, params)
    )


async def list_personas(session: AsyncSession, user_id: uuid.UUID) -> list[Persona]:
    rows = await session.scalars(
        select(Persona).where(Persona.user_id == user_id).order_by(func.lower(Persona.name))
    )
    return list(rows)


async def get_persona(session: AsyncSession, user_id: uuid.UUID, persona_id: uuid.UUID) -> Persona:
    persona = await session.scalar(
        select(Persona).where(Persona.id == persona_id, Persona.user_id == user_id)
    )
    if persona is None:
        raise PersonaNotFound
    return persona


async def _name_taken(
    session: AsyncSession, user_id: uuid.UUID, name: str, except_id: uuid.UUID | None = None
) -> bool:
    query = select(Persona.id).where(
        Persona.user_id == user_id, func.lower(Persona.name) == name.lower()
    )
    if except_id is not None:
        query = query.where(Persona.id != except_id)
    return await session.scalar(query) is not None


async def create_persona(session: AsyncSession, user_id: uuid.UUID, data: PersonaIn) -> Persona:
    if errors := _voice_errors(data.tts_provider, data.voice_params):
        raise FieldValidationError(errors)
    if await _name_taken(session, user_id, data.name):
        raise PersonaConflict(f"There is already a persona called '{data.name}'")
    persona = Persona(
        user_id=user_id,
        name=data.name,
        persona=data.persona,
        tts_provider=data.tts_provider,
        voice_id=data.voice_id,
        voice_params=dict(data.voice_params),
    )
    session.add(persona)
    try:
        await session.commit()
    except IntegrityError as exc:  # lost a race for the name
        await session.rollback()
        raise PersonaConflict(f"There is already a persona called '{data.name}'") from exc
    await session.refresh(persona)
    return persona


async def update_persona(
    session: AsyncSession, user_id: uuid.UUID, persona_id: uuid.UUID, data: PersonaUpdate
) -> Persona:
    persona = await get_persona(session, user_id, persona_id)
    changed = data.model_fields_set

    if "name" in changed and data.name is not None:
        if await _name_taken(session, user_id, data.name, except_id=persona.id):
            raise PersonaConflict(f"There is already a persona called '{data.name}'")
        persona.name = data.name
    if "persona" in changed and data.persona is not None:
        persona.persona = data.persona

    provider = data.tts_provider if "tts_provider" in changed else persona.tts_provider
    voice = data.voice_id if "voice_id" in changed else persona.voice_id
    if (provider is None) != (voice is None):
        raise FieldValidationError(
            [FieldError(("body", "voice_id"), "A default voice needs both a provider and a voice")]
        )
    params: Mapping[str, object] = (
        data.voice_params
        if "voice_params" in changed and data.voice_params is not None
        else persona.voice_params
    )
    if provider is None:
        params = {}  # no voice, no settings
    if errors := _voice_errors(provider, params):
        raise FieldValidationError(errors)
    persona.tts_provider, persona.voice_id, persona.voice_params = provider, voice, dict(params)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise PersonaConflict("There is already a persona with that name") from exc
    await session.refresh(persona)
    return persona


async def delete_persona(session: AsyncSession, user_id: uuid.UUID, persona_id: uuid.UUID) -> None:
    await session.delete(await get_persona(session, user_id, persona_id))
    await session.commit()
