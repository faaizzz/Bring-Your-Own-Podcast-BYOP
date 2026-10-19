import asyncio
import tracemalloc
import uuid
from collections.abc import Callable, Mapping
from decimal import Decimal
from pathlib import Path

import anyio
import pytest

from byop.models.enums import CredentialProvider
from byop.providers.tts import CallMetadata, TTSError, TTSParamError, TTSProvider
from byop.providers.tts.base import AudioRequest, ProviderQuirks, TTSResult, Voice
from byop.services.provider_ref import ProviderRef
from byop.services.synthesis import (
    Chunk,
    ChunkAudio,
    ChunkFailed,
    Segment,
    SpeakerVoice,
    plan_chunks,
    synthesize_chunks,
)


class P:
    """Built-in providers as the references shows and speakers store."""

    OPENAI = ProviderRef.of(CredentialProvider.OPENAI)
    OPENROUTER = ProviderRef.of(CredentialProvider.OPENROUTER)
    ELEVENLABS = ProviderRef.of(CredentialProvider.ELEVENLABS)
    KOKORO = ProviderRef.of(CredentialProvider.KOKORO)


class FakeTTS(TTSProvider):
    """A provider that writes small files and misbehaves on demand; no network, no HTTP client."""

    name = "fake"
    quirks = ProviderQuirks(
        max_chars_per_request=100, formats={}, default_format="pcm", supported_params=frozenset()
    )

    def __init__(
        self,
        *,
        limit: int = 100,
        delay: Callable[[str], float] = lambda text: 0.0,
        fail: Callable[[str, int], Exception | None] = lambda text, n: None,
        cost: Decimal | None = None,
        file_bytes: int | None = None,
        max_concurrency: int | None = None,
    ) -> None:
        self.quirks = ProviderQuirks(  # type: ignore[misc]
            max_chars_per_request=limit,
            formats={},
            default_format="pcm",
            supported_params=frozenset(),
            max_concurrency=max_concurrency,
        )
        self.limit = limit
        self.delay = delay
        self.fail = fail
        self.cost = cost
        self.file_bytes = file_bytes
        self.calls: list[tuple[str, str, Mapping[str, object]]] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self.closed = False

    @property
    def max_chars_per_request(self) -> int:
        return self.limit

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str,
        output_dir: Path,
        params: Mapping[str, object] | None = None,
        metadata: CallMetadata | None = None,
    ) -> TTSResult:
        self.calls.append((text, voice_id, dict(params or {})))
        attempts = sum(1 for call in self.calls if call[0] == text)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay(text))
            if (error := self.fail(text, attempts)) is not None:
                raise error
            await anyio.Path(output_dir).mkdir(parents=True, exist_ok=True)
            path = output_dir / f"{uuid.uuid4().hex}.wav"
            async with await anyio.open_file(path, "wb") as out:
                if self.file_bytes:
                    block = b"x" * 65536
                    for _ in range(self.file_bytes // len(block)):
                        await out.write(block)
                else:
                    await out.write(text.encode())  # the content says which chunk this is
            return TTSResult(path, "wav", 24000, len(text), self.cost, 3)
        finally:
            self.in_flight -= 1

    def build_request(self, *args: object, **kwargs: object) -> AudioRequest:
        raise NotImplementedError

    async def list_voices(self) -> list[Voice]:
        return []

    async def aclose(self) -> None:
        self.closed = True


class Recorder:
    def __init__(self) -> None:
        self.done: list[tuple[int, int, int]] = []

    async def chunk_done(self, audio: ChunkAudio, done: int, total: int) -> None:
        self.done.append((audio.index, done, total))


ALEX = SpeakerVoice("Alex", P.OPENAI, "alloy", {"speed": 1.1})
SAM = SpeakerVoice("Sam", P.ELEVENLABS, "rachel")
VOICES = {"Alex": ALEX, "Sam": SAM}


async def run(
    chunks: list[Chunk],
    pool: Mapping[ProviderRef, TTSProvider],
    work: Path,
    voices: Mapping[str, SpeakerVoice] = VOICES,
    *,
    concurrency: int = 4,
    retries: int = 0,
    reporter: Recorder | None = None,
) -> list[ChunkAudio]:
    return await synthesize_chunks(
        chunks, voices, pool, work,
        concurrency=concurrency, retries=retries, backoff_s=0.0,
        reporter=reporter or Recorder(),
    )  # fmt: skip


def chunks_of(*texts: str, speaker: str = "Alex") -> list[Chunk]:
    return [Chunk(i, i, "story", speaker, t) for i, t in enumerate(texts)]


def content(audio: ChunkAudio) -> str:
    return "".join(f.read_text() for f in audio.files)


# --- planning ---------------------------------------------------------------------------------


def test_chunks_follow_each_speakers_provider_limit_and_never_mix_speakers() -> None:
    segments = [
        Segment("Alex", "One. Two. Three. Four.", "intro"),
        Segment("Sam", "Alpha beta gamma delta epsilon zeta.", "story"),
        Segment("Alex", "Short.", "outro"),
    ]

    chunks = plan_chunks(segments, VOICES, {P.OPENAI: 12, P.ELEVENLABS: 100})

    assert [(c.index, c.segment, c.speaker, c.kind) for c in chunks] == [
        (0, 0, "Alex", "intro"),
        (1, 0, "Alex", "intro"),
        (2, 1, "Sam", "story"),
        (3, 2, "Alex", "outro"),
    ]
    assert [c.text for c in chunks][:2] == ["One. Two.", "Three. Four."]  # cut at sentence ends
    assert all(len(c.text) <= 12 for c in chunks if c.speaker == "Alex")
    assert chunks[2].text == "Alpha beta gamma delta epsilon zeta."  # Sam's limit is larger


# --- ordering and concurrency ---------------------------------------------------------------


async def test_the_result_is_in_script_order_even_when_later_chunks_finish_first(
    tmp_path: Path,
) -> None:
    texts = [f"chunk {n}" for n in range(8)]
    fake = FakeTTS(delay=lambda text: (8 - int(text.split()[1])) * 0.01)  # the last is fastest
    recorder = Recorder()

    audio = await run(chunks_of(*texts), {P.OPENAI: fake}, tmp_path, reporter=recorder)

    assert [a.index for a in audio] == list(range(8))
    assert [content(a) for a in audio] == texts
    finished = [index for index, _, _ in recorder.done]
    assert finished != sorted(finished)  # they really did complete out of order
    assert [(d, t) for _, d, t in recorder.done] == [(n, 8) for n in range(1, 9)]


async def test_no_more_than_the_configured_number_of_chunks_run_at_once(tmp_path: Path) -> None:
    fake = FakeTTS(delay=lambda text: 0.02)

    await run(chunks_of(*[f"c{n}" for n in range(15)]), {P.OPENAI: fake}, tmp_path, concurrency=3)
    assert fake.max_in_flight == 3

    serial = FakeTTS(delay=lambda text: 0.005)
    await run(chunks_of(*[f"c{n}" for n in range(6)]), {P.OPENAI: serial}, tmp_path, concurrency=1)
    assert serial.max_in_flight == 1


async def test_each_speaker_uses_their_own_provider_voice_and_settings(tmp_path: Path) -> None:
    openai, eleven = FakeTTS(), FakeTTS()
    chunks = [
        Chunk(0, 0, "intro", "Alex", "Hello from Alex"),
        Chunk(1, 1, "story", "Sam", "Hello from Sam"),
    ]

    audio = await run(chunks, {P.OPENAI: openai, P.ELEVENLABS: eleven}, tmp_path)

    assert openai.calls == [("Hello from Alex", "alloy", {"speed": 1.1})]
    assert eleven.calls == [("Hello from Sam", "rachel", {})]
    assert [(a.provider, a.voice_id, a.used_fallback) for a in audio] == [
        ("openai", "alloy", False),
        ("elevenlabs", "rachel", False),
    ]


async def test_nothing_to_voice_is_fine(tmp_path: Path) -> None:
    assert await run([], {}, tmp_path) == []


# --- usage numbers ----------------------------------------------------------------------------


async def test_characters_cost_and_latency_are_recorded_per_chunk(tmp_path: Path) -> None:
    paid = FakeTTS(cost=Decimal("0.0015"))
    free = FakeTTS()

    audio = await run(
        [Chunk(0, 0, "story", "Alex", "twelve chars"), Chunk(1, 1, "story", "Sam", "ten chars!")],
        {P.OPENAI: paid, P.ELEVENLABS: free},
        tmp_path,
    )

    assert [(a.characters, a.cost_usd, a.latency_ms) for a in audio] == [
        (12, Decimal("0.0015"), 3),
        (10, None, 3),
    ]


# --- retries and fallback -------------------------------------------------------------------------


VOICE_WITH_FALLBACK = {
    "Alex": SpeakerVoice(
        "Alex",
        P.OPENAI,
        "alloy",
        {"speed": 1.2},
        fallback_provider=P.KOKORO,
        fallback_voice_id="af_bella",
    )
}


def fail_when(marker: str, error: Exception) -> Callable[[str, int], Exception | None]:
    return lambda text, attempt: error if marker in text else None


async def test_a_failing_chunk_uses_the_fallback_voice_and_only_that_chunk(tmp_path: Path) -> None:
    primary = FakeTTS(fail=fail_when("BAD", TTSError("HTTP 500", status_code=500)))
    fallback = FakeTTS()
    chunks = chunks_of("fine one", "BAD chunk", "fine two")

    audio = await run(
        chunks, {P.OPENAI: primary, P.KOKORO: fallback}, tmp_path, VOICE_WITH_FALLBACK
    )

    assert [a.used_fallback for a in audio] == [False, True, False]
    assert [a.provider for a in audio] == ["openai", "kokoro", "openai"]
    assert audio[1].voice_id == "af_bella" and "HTTP 500" in (audio[1].fallback_reason or "")
    assert [c[0] for c in fallback.calls] == ["BAD chunk"]
    assert fallback.calls[0][2] == {}  # a fallback carries no voice settings
    assert [content(a) for a in audio] == ["fine one", "BAD chunk", "fine two"]


async def test_a_chunk_is_retried_before_the_fallback_is_used(tmp_path: Path) -> None:
    flaky = FakeTTS(fail=lambda text, attempt: TTSError("busy") if attempt < 3 else None)
    fallback = FakeTTS()

    healed = await run(chunks_of("one chunk"), {P.OPENAI: flaky, P.KOKORO: fallback}, tmp_path,
                       VOICE_WITH_FALLBACK, retries=2)  # fmt: skip
    assert not healed[0].used_fallback and len(flaky.calls) == 3 and fallback.calls == []

    stubborn = FakeTTS(fail=lambda text, attempt: TTSError("busy") if attempt < 4 else None)
    gave_up = await run(chunks_of("one chunk"), {P.OPENAI: stubborn, P.KOKORO: fallback}, tmp_path,
                        VOICE_WITH_FALLBACK, retries=1)  # fmt: skip
    assert gave_up[0].used_fallback and len(stubborn.calls) == 2


async def test_a_request_the_provider_rejects_is_not_retried(tmp_path: Path) -> None:
    primary = FakeTTS(fail=lambda text, attempt: TTSParamError("speed is not supported"))
    fallback = FakeTTS()

    audio = await run(chunks_of("hello"), {P.OPENAI: primary, P.KOKORO: fallback}, tmp_path,
                      VOICE_WITH_FALLBACK, retries=5)  # fmt: skip

    assert len(primary.calls) == 1  # no pointless retries
    assert audio[0].used_fallback and "speed is not supported" in (audio[0].fallback_reason or "")


async def test_without_a_fallback_a_failing_chunk_fails_the_whole_job(tmp_path: Path) -> None:
    primary = FakeTTS(fail=fail_when("BAD", TTSError("HTTP 500", status_code=500)))

    with pytest.raises(ChunkFailed) as caught:
        await run(chunks_of("fine", "BAD chunk"), {P.OPENAI: primary}, tmp_path, retries=1)

    assert (
        str(caught.value) == "Chunk 2 (Alex, openai): HTTP 500. The speaker has no fallback voice."
    )
    assert len([c for c in primary.calls if "BAD" in c[0]]) == 2  # the retry happened first


async def test_when_the_fallback_fails_too_both_reasons_are_reported(tmp_path: Path) -> None:
    primary = FakeTTS(fail=lambda text, attempt: TTSError("primary down"))
    fallback = FakeTTS(fail=lambda text, attempt: TTSError("fallback down"))

    with pytest.raises(ChunkFailed) as caught:
        await run(chunks_of("hello"), {P.OPENAI: primary, P.KOKORO: fallback}, tmp_path,
                  VOICE_WITH_FALLBACK)  # fmt: skip

    message = str(caught.value)
    assert "primary down" in message and "fallback down" in message and "kokoro" in message


async def test_a_fallback_provider_that_is_not_set_up_is_reported(tmp_path: Path) -> None:
    primary = FakeTTS(fail=lambda text, attempt: TTSError("down"))

    with pytest.raises(ChunkFailed, match=r"fallback provider \(kokoro\) is not set up"):
        await run(chunks_of("hello"), {P.OPENAI: primary}, tmp_path, VOICE_WITH_FALLBACK)


async def test_a_missing_primary_provider_goes_straight_to_the_fallback(tmp_path: Path) -> None:
    fallback = FakeTTS()

    audio = await run(chunks_of("hello"), {P.KOKORO: fallback}, tmp_path, VOICE_WITH_FALLBACK)

    assert audio[0].used_fallback and audio[0].fallback_reason == "the provider is not available"


async def test_a_fallback_with_a_smaller_limit_voices_the_chunk_in_pieces(tmp_path: Path) -> None:
    text = "One short sentence. Another short sentence. A third short one. And a last one here."
    primary = FakeTTS(limit=200, fail=lambda t, n: TTSError("down"))
    fallback = FakeTTS(limit=45)

    audio = await run(chunks_of(text), {P.OPENAI: primary, P.KOKORO: fallback}, tmp_path,
                      VOICE_WITH_FALLBACK)  # fmt: skip

    [result] = audio
    assert result.used_fallback and len(result.files) == 2
    assert all(len(call[0]) <= 45 for call in fallback.calls)
    assert result.characters == sum(len(call[0]) for call in fallback.calls)
    assert [f.name for f in result.files] == ["00000-0.wav", "00000-1.wav"]  # in order
    assert " ".join(f.read_text() for f in result.files).replace("  ", " ") == " ".join(
        c[0] for c in fallback.calls
    )


# --- stopping early ---------------------------------------------------------------------------


async def test_the_first_chunk_that_fails_stops_the_others(tmp_path: Path) -> None:
    primary = FakeTTS(
        delay=lambda text: 0.0 if "BAD" in text else 0.05,
        fail=fail_when("BAD", TTSError("boom")),
    )
    texts = ["BAD first"] + [f"slow {n}" for n in range(30)]

    with pytest.raises(ChunkFailed):
        await run(chunks_of(*texts), {P.OPENAI: primary}, tmp_path, concurrency=4)

    assert len(primary.calls) < len(texts)  # most of the script was never started
    await asyncio.sleep(0.1)
    assert primary.in_flight == 0  # and nothing is left running


async def test_a_reporter_that_raises_stops_the_rest_with_its_own_error(tmp_path: Path) -> None:
    class Stopped(Exception):
        """Stands in for `RunStopped`, which a cancelled run raises through `checkpoint()`."""

    class Stopper(Recorder):
        async def chunk_done(self, audio: ChunkAudio, done: int, total: int) -> None:
            if done == 2:
                raise Stopped

    fake = FakeTTS(delay=lambda text: 0.02)

    with pytest.raises(Stopped):
        await run(chunks_of(*[f"c{n}" for n in range(20)]), {P.OPENAI: fake}, tmp_path,
                  concurrency=2, reporter=Stopper())  # fmt: skip

    await asyncio.sleep(0.1)
    assert len(fake.calls) < 20 and fake.in_flight == 0


# --- memory -------------------------------------------------------------------------------------


async def test_memory_stays_flat_however_much_audio_is_produced(tmp_path: Path) -> None:
    # 40 chunks of 2 MB each: 80 MB of audio on disk. Holding it in memory would show up at once.
    fake = FakeTTS(file_bytes=2 * 1024 * 1024)
    tracemalloc.start()
    try:
        audio = await run(chunks_of(*[f"chunk {n}" for n in range(40)]), {P.OPENAI: fake}, tmp_path,
                          concurrency=4)  # fmt: skip
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert sum(f.stat().st_size for a in audio for f in a.files) == 40 * 2 * 1024 * 1024
    assert peak < 5 * 1024 * 1024, f"peaked at {peak / 1024 / 1024:.1f} MB"


async def test_cancelling_the_job_cancels_every_chunk(tmp_path: Path) -> None:
    fake = FakeTTS(delay=lambda text: 0.5)
    job = asyncio.ensure_future(
        run(chunks_of(*[f"c{n}" for n in range(10)]), {P.OPENAI: fake}, tmp_path, concurrency=4)
    )
    await asyncio.sleep(0.05)

    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job

    await asyncio.sleep(0.05)
    assert fake.in_flight == 0


async def test_the_reporter_is_never_run_twice_at_once(tmp_path: Path) -> None:
    class Strict(Recorder):
        def __init__(self) -> None:
            super().__init__()
            self.inside = False
            self.overlapped = False

        async def chunk_done(self, audio: ChunkAudio, done: int, total: int) -> None:
            self.overlapped = self.overlapped or self.inside
            self.inside = True
            await asyncio.sleep(0.005)  # slower than the chunks, so completions queue up
            self.inside = False
            await super().chunk_done(audio, done, total)

    strict = Strict()
    fake = FakeTTS(delay=lambda text: 0.001)

    await run(chunks_of(*[f"c{n}" for n in range(12)]), {P.OPENAI: fake}, tmp_path,
              concurrency=6, reporter=strict)  # fmt: skip

    assert not strict.overlapped and len(strict.done) == 12


async def test_a_provider_that_takes_one_request_at_a_time_is_never_sent_two(
    tmp_path: Path,
) -> None:
    one_at_a_time = FakeTTS(delay=lambda text: 0.01, max_concurrency=1)
    free = FakeTTS(delay=lambda text: 0.01)
    mixed = [Chunk(i, i, "story", "Alex" if i % 2 == 0 else "Sam", f"chunk {i}") for i in range(16)]

    audio = await run(mixed, {P.OPENAI: one_at_a_time, P.ELEVENLABS: free}, tmp_path, concurrency=6)

    assert one_at_a_time.max_in_flight == 1
    assert free.max_in_flight > 1  # the other provider still works in parallel
    assert [content(a) for a in audio] == [f"chunk {i}" for i in range(16)]


async def test_waiting_for_a_busy_provider_does_not_block_another_provider(
    tmp_path: Path,
) -> None:
    slow = FakeTTS(delay=lambda text: 0.05, max_concurrency=1)
    fast = FakeTTS()
    # Many chunks for the slow provider first, then a few for the fast one, with only 2 slots.
    chunks = [Chunk(i, i, "story", "Alex", f"slow {i}") for i in range(6)]
    chunks += [Chunk(6 + i, 6 + i, "story", "Sam", f"fast {i}") for i in range(3)]
    finished: list[str] = []

    class Order(Recorder):
        async def chunk_done(self, audio: ChunkAudio, done: int, total: int) -> None:
            finished.append(audio.speaker)

    await run(
        chunks, {P.OPENAI: slow, P.ELEVENLABS: fast}, tmp_path, concurrency=2, reporter=Order()
    )

    # The fast provider's chunks do not wait behind all six slow ones.
    assert finished.index("Sam") < 4
