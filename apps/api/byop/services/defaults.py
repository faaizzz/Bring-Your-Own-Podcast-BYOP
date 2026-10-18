import uuid

from byop.models.enums import CredentialProvider
from byop.services.credentials import CredentialResolver, ProviderNotConfigured
from byop.services.integration_check import check_provider

# Paid providers in order of preference; Kokoro (free, local) is the fallback.
PAID_TTS_PROVIDERS = (
    CredentialProvider.ELEVENLABS,
    CredentialProvider.OPENAI,
    CredentialProvider.OPENROUTER,
)


async def default_tts_provider(
    resolver: CredentialResolver, user_id: uuid.UUID
) -> CredentialProvider | None:
    """The TTS provider to preselect: a configured paid one, else Kokoro if it is running."""
    for provider in PAID_TTS_PROVIDERS:
        try:
            await resolver.get(user_id, provider)
        except ProviderNotConfigured:
            continue
        return provider
    try:
        kokoro = await resolver.get(user_id, CredentialProvider.KOKORO)
    except ProviderNotConfigured:
        return None
    # Kokoro's URL may be preconfigured by compose even when its profile is not running.
    return CredentialProvider.KOKORO if (await check_provider(kokoro)).ok else None
