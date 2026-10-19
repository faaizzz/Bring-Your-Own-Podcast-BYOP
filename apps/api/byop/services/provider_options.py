"""What a provider picker offers: the built-in providers plus the user's connections."""

import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import ProviderConnection
from byop.models.enums import CredentialProvider
from byop.schemas.providers import ProviderOption
from byop.services.credentials import (
    CredentialDecryptionError,
    CredentialResolver,
    ProviderNotConfigured,
)
from byop.services.provider_ref import CONNECTION_PREFIX

Capability = Literal["llm", "tts"]
Use = Literal["llm", "tts", "web_search"]

_BUILTIN: tuple[tuple[CredentialProvider, str, tuple[Capability, ...]], ...] = (
    (CredentialProvider.OPENROUTER, "OpenRouter", ("llm", "tts")),
    (CredentialProvider.OPENAI, "OpenAI", ("llm", "tts")),
    (CredentialProvider.ELEVENLABS, "ElevenLabs", ("tts",)),
    (CredentialProvider.KOKORO, "Kokoro (local)", ("tts",)),
)


async def _configured(
    resolver: CredentialResolver, user_id: uuid.UUID, p: CredentialProvider
) -> bool:
    try:
        await resolver.get(user_id, p)
    except (ProviderNotConfigured, CredentialDecryptionError):
        return False
    return True


async def provider_options(
    session: AsyncSession,
    resolver: CredentialResolver,
    user_id: uuid.UUID,
    capability: Capability,
) -> list[ProviderOption]:
    options = [
        ProviderOption(
            id=provider.value,
            label=label,
            kind="builtin",
            configured=await _configured(resolver, user_id, provider),
            capabilities=list(capabilities),
        )
        for provider, label, capabilities in _BUILTIN
        if capability in capabilities
    ]
    rows = await session.scalars(
        select(ProviderConnection)
        .where(ProviderConnection.user_id == user_id, getattr(ProviderConnection, capability))
        .order_by(ProviderConnection.name)
    )
    for record in rows:
        uses: list[Use] = []
        if record.llm:
            uses.append("llm")
        if record.tts:
            uses.append("tts")
        if record.web_search:
            uses.append("web_search")
        options.append(
            ProviderOption(
                id=f"{CONNECTION_PREFIX}{record.id}",
                label=record.name,
                kind="connection",
                configured=record.enabled,
                capabilities=uses,
            )
        )
    return options
