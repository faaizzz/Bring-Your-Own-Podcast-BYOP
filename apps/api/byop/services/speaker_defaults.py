from byop.models.enums import CredentialProvider
from byop.schemas.speaker import SpeakerIn

HOST_PERSONAS = (
    (
        "Alex",
        "The lead host. Curious, warm and well prepared; introduces each story, explains "
        "why it matters and keeps the conversation moving.",
    ),
    (
        "Sam",
        "The co-host. Sharp and a little skeptical; adds context, asks the follow-up "
        "questions a listener would ask and keeps things light.",
    ),
)

# Two distinct voices per provider (voice id, extra voice parameters).
_VOICES: dict[CredentialProvider, tuple[tuple[str, dict[str, str | float]], ...]] = {
    CredentialProvider.OPENAI: (("alloy", {}), ("nova", {})),
    CredentialProvider.ELEVENLABS: (
        ("21m00Tcm4TlvDq8ikWAM", {}),  # Rachel
        ("pNInz6obpgDQGcFmaJgB", {}),  # Adam
    ),
    # OpenRouter has no default speech model, so the speakers must name one.
    CredentialProvider.OPENROUTER: (
        ("alloy", {"model": "openai/gpt-4o-mini-tts"}),
        ("nova", {"model": "openai/gpt-4o-mini-tts"}),
    ),
    CredentialProvider.KOKORO: (("af_bella", {}), ("am_michael", {})),
}


def default_speakers(provider: CredentialProvider) -> list[SpeakerIn]:
    """Two hosts with distinct voices on `provider`."""
    return [
        SpeakerIn(
            name=name,
            persona=persona,
            tts_provider=provider.value,
            voice_id=voice_id,
            voice_params=dict(params),
        )
        for (name, persona), (voice_id, params) in zip(
            HOST_PERSONAS, _VOICES[provider], strict=True
        )
    ]
