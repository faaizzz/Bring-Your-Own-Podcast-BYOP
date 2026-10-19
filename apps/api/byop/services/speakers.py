import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Speaker
from byop.providers.tts import quirks_for, voice_param_problems
from byop.schemas.speaker import SpeakerIn
from byop.services.connections import connection_problems
from byop.services.provider_ref import ProviderRef
from byop.services.shows import get_show
from byop.services.validation import FieldError, FieldValidationError, param_errors


def validate_speakers(speakers: Sequence[SpeakerIn]) -> list[FieldError]:
    """Every problem in the list, each located at the offending field."""
    errors: list[FieldError] = []
    seen: dict[str, int] = {}
    for index, speaker in enumerate(speakers):
        key = speaker.name.casefold()
        if key in seen:
            errors.append(
                FieldError(
                    ("body", index, "name"),
                    f"Speaker names must be unique; '{speaker.name}' repeats",
                )
            )
        seen.setdefault(key, index)

        provider = ProviderRef.parse(speaker.tts_provider)
        errors += param_errors(
            ("body", index, "voice_params"),
            voice_param_problems(provider.kind, speaker.voice_params),
        )

        if (speaker.fallback_tts_provider is None) != (speaker.fallback_voice_id is None):
            field = (
                "fallback_voice_id" if speaker.fallback_tts_provider else "fallback_tts_provider"
            )
            errors.append(
                FieldError(("body", index, field), "A fallback needs both a provider and a voice")
            )
        elif speaker.fallback_tts_provider is not None:
            fallback = ProviderRef.parse(speaker.fallback_tts_provider)
            # A fallback carries no voice parameters, so it must work without any.
            if quirks_for(fallback.kind).required_params:
                errors.append(
                    FieldError(
                        ("body", index, "fallback_tts_provider"),
                        f"{fallback.kind.value} needs voice parameters, which a fallback "
                        "cannot carry",
                    )
                )
    return errors


async def list_speakers(
    session: AsyncSession, user_id: uuid.UUID, show_id: uuid.UUID
) -> list[Speaker]:
    await get_show(session, user_id, show_id)  # 404 for someone else's show
    return await _ordered(session, user_id, show_id)


async def _ordered(session: AsyncSession, user_id: uuid.UUID, show_id: uuid.UUID) -> list[Speaker]:
    rows = await session.scalars(
        select(Speaker)
        .where(Speaker.show_id == show_id, Speaker.user_id == user_id)
        .order_by(Speaker.position)
    )
    return list(rows)


async def replace_speakers(
    session: AsyncSession,
    user_id: uuid.UUID,
    show_id: uuid.UUID,
    speakers: Sequence[SpeakerIn],
) -> list[Speaker]:
    """Make the show's speakers exactly `speakers`, in that order.

    Rows are reused by position so the first speakers keep their ids.
    """
    await get_show(session, user_id, show_id)
    errors = validate_speakers(speakers)
    errors += await connection_problems(session, user_id, speakers)
    if errors:
        raise FieldValidationError(errors)

    existing = await _ordered(session, user_id, show_id)
    for position, data in enumerate(speakers):
        row = existing[position] if position < len(existing) else None
        if row is None:
            row = Speaker(user_id=user_id, show_id=show_id, position=position)
            session.add(row)
        row.name = data.name
        row.persona = data.persona
        row.tts_provider = data.tts_provider
        row.voice_id = data.voice_id
        row.voice_params = dict(data.voice_params)
        row.fallback_tts_provider = data.fallback_tts_provider
        row.fallback_voice_id = data.fallback_voice_id
    for surplus in existing[len(speakers) :]:
        await session.delete(surplus)
    await session.commit()
    return await _ordered(session, user_id, show_id)
