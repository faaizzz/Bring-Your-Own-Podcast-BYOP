import uuid

from byop.models.enums import CredentialProvider
from byop.services.credentials import CredentialResolver, ProviderNotConfigured
from byop.services.integration_check import check_provider

# The default is looked up on every dashboard load, so a dead Kokoro URL must not stall it.
KOKORO_PROBE_SECONDS = 2.0

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
    # A configured URL says nothing about whether the server runs (`make up-full` sets it, a
    # hand-written one may be stale), so ask it.
    probe = await check_provider(kokoro, timeout_seconds=KOKORO_PROBE_SECONDS)
    return CredentialProvider.KOKORO if probe.ok else None
