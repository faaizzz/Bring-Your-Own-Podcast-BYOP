"""Voicing a script: chunk it, synthesize the chunks concurrently, keep their order.

Audio never passes through memory here: providers stream to files, and this module only holds
paths and counts.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager, nullcontext
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Protocol

import anyio
import structlog

from byop.providers.tts import CallMetadata, TTSError, TTSParamError, TTSProvider
from byop.services.provider_ref import ProviderRef
from byop.services.tts_chunks import split_text

log = structlog.get_logger(__name__)

STAGE = "tts"


class ChunkFailed(Exception):
    """A chunk could not be voiced by its speaker's voice or by the fallback."""


@dataclass(frozen=True)
class SpeakerVoice:
    name: str
    provider: ProviderRef
    voice_id: str
    params: Mapping[str, object] = field(default_factory=dict)
    fallback_provider: ProviderRef | None = None
    fallback_voice_id: str | None = None


@dataclass(frozen=True)
class Segment:
    speaker: str
    text: str
    kind: str = "story"


@dataclass(frozen=True)
class Chunk:
    index: int  # position in the whole episode, from 0
    segment: int  # which segment of the script it belongs to
    kind: str
    speaker: str
    text: str


@dataclass
class ChunkAudio:
    """The audio of one chunk, and what it took to make: the numbers usage capture needs."""

    index: int
    segment: int
    kind: str
    speaker: str
    files: list[Path]  # normally one; several if a fallback with a smaller limit had to split it
    provider: str
    voice_id: str
    characters: int
    cost_usd: Decimal | None
    latency_ms: int
    used_fallback: bool = False
    fallback_reason: str | None = None


class Reporter(Protocol):
    async def chunk_done(self, audio: ChunkAudio, done: int, total: int) -> None: ...


def plan_chunks(
    segments: Sequence[Segment],
    voices: Mapping[str, SpeakerVoice],
    limits: Mapping[ProviderRef, int],
) -> list[Chunk]:
    """Split every segment at sentence boundaries into chunks its speaker's provider accepts.

    A chunk belongs to exactly one segment, so it never mixes speakers.
    """
    chunks: list[Chunk] = []
    for number, segment in enumerate(segments):
        voice = voices[segment.speaker]
        for text in split_text(segment.text, limits[voice.provider]):
            chunks.append(Chunk(len(chunks), number, segment.kind, segment.speaker, text))
    return chunks


class _Gates:
    """Limits on how many requests run at once: overall, and per provider that asks for it."""

    def __init__(self, concurrency: int, pool: Mapping[ProviderRef, TTSProvider]) -> None:
        self._overall = asyncio.Semaphore(concurrency)
        self._providers = {
            id(p): asyncio.Semaphore(p.quirks.max_concurrency)
            for p in pool.values()
            if p.quirks.max_concurrency is not None
        }

    @asynccontextmanager
    async def slot(self, provider: TTSProvider) -> AsyncIterator[None]:
        # The provider's own limit first, so tasks waiting for it do not hold an overall slot
        # that another provider's chunk could use.
        own = self._providers.get(id(provider))
        async with own if own is not None else nullcontext(), self._overall:
            yield


async def _speak(
    gates: _Gates,
    provider: TTSProvider,
    voice_id: str,
    params: Mapping[str, object],
    chunk: Chunk,
    work: Path,
    metadata: CallMetadata,
) -> tuple[list[Path], int, Decimal | None, int]:
    """Synthesize the chunk (in pieces if this provider's limit is smaller) into `work`."""
    files: list[Path] = []
    characters, latency = 0, 0
    cost: Decimal | None = None
    for number, piece in enumerate(split_text(chunk.text, provider.max_chars_per_request)):
        async with gates.slot(provider):
            result = await provider.synthesize(
                piece, voice_id=voice_id, output_dir=work, params=params, metadata=metadata
            )
        target = work / f"{chunk.index:05d}-{number}.wav"
        await anyio.Path(result.audio_path).replace(target)
        files.append(target)
        characters += result.characters
        latency += result.latency_ms
        if result.cost_usd is not None:
            cost = (cost or Decimal(0)) + result.cost_usd
    return files, characters, cost, latency


async def _synthesize_chunk(
    chunk: Chunk,
    voice: SpeakerVoice,
    pool: Mapping[ProviderRef, TTSProvider],
    work: Path,
    gates: _Gates,
    *,
    retries: int,
    backoff_s: float,
    metadata: CallMetadata,
) -> ChunkAudio:
    """Voice one chunk: the speaker's voice (retried), else their fallback voice, else fail."""
    meta = CallMetadata(
        show_id=metadata.show_id,
        run_id=metadata.run_id,
        stage=metadata.stage,
        tags={"chunk": str(chunk.index), "speaker": chunk.speaker},
    )
    primary_error = "the provider is not available"
    primary = pool.get(voice.provider)
    if primary is not None:
        for attempt in range(retries + 1):
            try:
                files, chars, cost, ms = await _speak(
                    gates, primary, voice.voice_id, voice.params, chunk, work, meta
                )
            except TTSParamError as exc:
                primary_error = str(exc)
                break  # the request itself is wrong; trying again changes nothing
            except TTSError as exc:
                primary_error = str(exc)
                log.warning(
                    "tts_chunk_failed", chunk=chunk.index, attempt=attempt + 1, error=primary_error
                )
                if attempt < retries:
                    await asyncio.sleep(backoff_s * 2**attempt)
            else:
                return ChunkAudio(
                    chunk.index, chunk.segment, chunk.kind, chunk.speaker, files,
                    str(voice.provider), voice.voice_id, chars, cost, ms,
                )  # fmt: skip

    where = f"Chunk {chunk.index + 1} ({chunk.speaker}, {str(voice.provider)})"
    if voice.fallback_provider is None or voice.fallback_voice_id is None:
        raise ChunkFailed(f"{where}: {primary_error}. The speaker has no fallback voice.")
    fallback = pool.get(voice.fallback_provider)
    if fallback is None:
        raise ChunkFailed(
            f"{where}: {primary_error}. The fallback provider "
            f"({str(voice.fallback_provider)}) is not set up."
        )
    try:
        files, chars, cost, ms = await _speak(
            gates, fallback, voice.fallback_voice_id, {}, chunk, work, meta
        )
    except TTSError as exc:
        raise ChunkFailed(
            f"{where}: {primary_error}. The fallback voice "
            f"({str(voice.fallback_provider)}) failed too: {exc}"
        ) from exc
    return ChunkAudio(
        chunk.index, chunk.segment, chunk.kind, chunk.speaker, files,
        str(voice.fallback_provider), voice.fallback_voice_id, chars, cost, ms,
        used_fallback=True, fallback_reason=primary_error,
    )  # fmt: skip


async def synthesize_chunks(
    chunks: Sequence[Chunk],
    voices: Mapping[str, SpeakerVoice],
    pool: Mapping[ProviderRef, TTSProvider],
    work: Path,
    *,
    concurrency: int,
    retries: int,
    backoff_s: float,
    reporter: Reporter,
    show_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
) -> list[ChunkAudio]:
    """Synthesize all chunks, at most `concurrency` at a time; the result is in chunk order.

    The chunk tasks only talk to the TTS providers. Their results are handed one at a time to
    `reporter` by the caller's own task, so the reporter may use the database without ever being
    interrupted or run twice at once. The first chunk that fails for good, or a reporter that
    raises (e.g. because the run was cancelled), cancels the remaining chunks and its error is
    raised as it is.
    """
    gates = _Gates(concurrency, pool)
    done: asyncio.Queue[ChunkAudio | Exception] = asyncio.Queue()
    metadata = CallMetadata(show_id=show_id, run_id=run_id, stage=STAGE)

    async def one(chunk: Chunk) -> None:
        try:
            done.put_nowait(
                await _synthesize_chunk(
                    chunk,
                    voices[chunk.speaker],
                    pool,
                    work,
                    gates,
                    retries=retries,
                    backoff_s=backoff_s,
                    metadata=metadata,
                )
            )
        except Exception as exc:
            done.put_nowait(exc)

    tasks = [asyncio.ensure_future(one(chunk)) for chunk in chunks]
    results: dict[int, ChunkAudio] = {}
    try:
        for _ in chunks:
            outcome = await done.get()
            if isinstance(outcome, Exception):
                raise outcome
            results[outcome.index] = outcome
            await reporter.chunk_done(outcome, len(results), len(chunks))
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return [results[chunk.index] for chunk in chunks]
