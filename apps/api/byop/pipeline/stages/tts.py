import json
from decimal import Decimal

import anyio
from sqlalchemy import select

from byop.models import Episode, Speaker
from byop.models.enums import CredentialProvider, EventLevel
from byop.pipeline.context import RunContext
from byop.pipeline.errors import StageFailed
from byop.pipeline.workdir import reset_dir, work_dir
from byop.providers.tts import TTSProvider, UnsupportedTTSProvider, get_tts
from byop.services.credentials import CredentialDecryptionError, ProviderNotConfigured
from byop.services.script_revision import revision_of
from byop.services.synthesis import (
    ChunkAudio,
    ChunkFailed,
    Segment,
    SpeakerVoice,
    plan_chunks,
    synthesize_chunks,
)

MANIFEST = "manifest.json"
MANIFEST_VERSION = 1


class _Reporter:
    """Progress and log lines as chunks finish. The engine calls it one chunk at a time, from
    this stage's own task, so it can use the run's database session freely."""

    def __init__(self, ctx: RunContext) -> None:
        self.ctx = ctx

    async def chunk_done(self, audio: ChunkAudio, done: int, total: int) -> None:
        if audio.used_fallback:
            await self.ctx.log(
                f"Chunk {audio.index + 1} ({audio.speaker}) used the fallback voice "
                f"({audio.provider}): {audio.fallback_reason}",
                level=EventLevel.WARNING,
                chunk=audio.index,
            )
        await self.ctx.progress(0.05 + 0.95 * done / total)
        await self.ctx.checkpoint()  # a cancelled run raises here and the other chunks stop


async def _voices(ctx: RunContext) -> dict[str, SpeakerVoice]:
    rows = await ctx.session.scalars(
        select(Speaker).where(Speaker.show_id == ctx.show.id, Speaker.user_id == ctx.user_id)
    )
    voices: dict[str, SpeakerVoice] = {}
    for row in rows:
        fallback = row.fallback_tts_provider
        voices[row.name] = SpeakerVoice(
            name=row.name,
            provider=CredentialProvider(row.tts_provider),
            voice_id=row.voice_id,
            params=dict(row.voice_params),
            fallback_provider=CredentialProvider(fallback) if fallback else None,
            fallback_voice_id=row.fallback_voice_id,
        )
    return voices


async def _providers(
    ctx: RunContext, voices: dict[str, SpeakerVoice], speaking: set[str]
) -> dict[CredentialProvider, TTSProvider]:
    """One client per provider the speakers use. A missing fallback provider only warns: it
    matters just if a chunk needs it."""
    primary = {voices[name].provider for name in speaking}
    fallbacks = {
        v.fallback_provider for n, v in voices.items() if n in speaking and v.fallback_provider
    }
    pool: dict[CredentialProvider, TTSProvider] = {}
    for provider in primary | {f for f in fallbacks if f}:
        try:
            pool[provider] = get_tts(provider, await ctx.resolver.get(ctx.user_id, provider))
        except (ProviderNotConfigured, CredentialDecryptionError, UnsupportedTTSProvider) as exc:
            message = (
                f"The {provider.value} voice provider is not set up: {exc}. Configure it under "
                "Settings › Integrations, or choose another voice for the speaker."
            )
            if provider in primary:
                await _close(pool)
                raise StageFailed(message) from exc
            await ctx.log(message, level=EventLevel.WARNING)
    return pool


async def _close(pool: dict[CredentialProvider, TTSProvider]) -> None:
    for provider in pool.values():
        await provider.aclose()


def _manifest(audio: list[ChunkAudio], base: anyio.Path, revision: int) -> dict[str, object]:
    total_cost = sum((a.cost_usd for a in audio if a.cost_usd is not None), Decimal(0))
    return {
        "version": MANIFEST_VERSION,
        "script_revision": revision,  # which version of the script this audio was voiced from
        "format": {"codec": "pcm_s16le", "sample_rate": 24000, "channels": 1},
        "characters": sum(a.characters for a in audio),
        "cost_usd": str(total_cost) if any(a.cost_usd is not None for a in audio) else None,
        "chunks": [
            {
                "index": a.index,
                "segment": a.segment,
                "kind": a.kind,
                "speaker": a.speaker,
                "files": [str(f.relative_to(base)) for f in a.files],
                "provider": a.provider,
                "voice_id": a.voice_id,
                "characters": a.characters,
                "cost_usd": str(a.cost_usd) if a.cost_usd is not None else None,
                "latency_ms": a.latency_ms,
                "fallback": a.used_fallback,
            }
            for a in audio
        ],
    }


async def run(ctx: RunContext) -> None:
    """Voice the script: one WAV per chunk in the run's work directory, plus a manifest."""
    await ctx.checkpoint()
    episode = await ctx.session.scalar(
        select(Episode).where(Episode.run_id == ctx.run.id, Episode.user_id == ctx.user_id)
    )
    raw = (episode.script or {}).get("segments") if episode else None
    if episode is None or not isinstance(raw, list) or not raw:
        raise StageFailed("There is no script to voice.")
    segments = [
        Segment(str(s["speaker"]), str(s["text"]), str(s.get("kind", "story"))) for s in raw
    ]

    voices = await _voices(ctx)
    unknown = sorted({s.speaker for s in segments} - voices.keys())
    if unknown:
        raise StageFailed(
            f"The script has lines for {', '.join(unknown)}, who is not a speaker of the show "
            "(was a speaker renamed or removed after the script was written?)."
        )
    pool = await _providers(ctx, voices, {s.speaker for s in segments})
    try:
        limits = {p: t.max_chars_per_request for p, t in pool.items()}
        chunks = plan_chunks(segments, voices, limits)
        if not chunks:
            raise StageFailed("The script has no text to voice.")
        base = await reset_dir(work_dir(ctx.settings.media_root, ctx.run.id))
        out = await reset_dir(base / "tts")
        await ctx.log(
            f"Voicing {len(chunks)} chunks of {len(segments)} segments, "
            f"{ctx.settings.tts_concurrency} at a time"
        )
        await ctx.progress(0.05)
        try:
            audio = await synthesize_chunks(
                chunks,
                voices,
                pool,
                out,
                concurrency=ctx.settings.tts_concurrency,
                retries=ctx.settings.tts_chunk_retries,
                backoff_s=ctx.settings.tts_retry_backoff_s,
                reporter=_Reporter(ctx),
                show_id=ctx.show.id,
                run_id=ctx.run.id,
            )
        except ChunkFailed as exc:
            raise StageFailed(f"Text-to-speech failed. {exc}") from exc
    finally:
        await _close(pool)

    manifest = _manifest(audio, anyio.Path(base), revision_of(episode.script))
    await anyio.Path(base / MANIFEST).write_text(json.dumps(manifest, indent=2))
    fallbacks = sum(1 for a in audio if a.used_fallback)
    await ctx.log(
        f"Voiced {len(audio)} chunks ({manifest['characters']} characters)"
        + (f"; {fallbacks} used a fallback voice" if fallbacks else ""),
        characters=manifest["characters"],
        cost_usd=manifest["cost_usd"],
        fallbacks=fallbacks,
    )
