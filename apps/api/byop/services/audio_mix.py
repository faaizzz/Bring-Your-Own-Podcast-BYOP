"""Turning voiced chunks into the finished episode: gaps, optional bed and clips, loudness, MP3.

Every step reads and writes files with ffmpeg; nothing holds audio in memory.
"""

import json
import re
import wave
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import anyio
import anyio.to_thread

from byop.services.ffmpeg import FFmpegError, duration_of, run_ffmpeg

OUTPUT_RATE = 44100
SPEECH_RATE = 24000  # the canonical format the TTS stage produces
CHUNK_GAP_MS = 100  # between the chunks of one line
TRUE_PEAK_DB = -1.5
LOUDNESS_RANGE = 11
MUSIC_FADE_S = 2.0
# The bed is pushed down while the speech is louder than this (linear; 0.01 is -40 dBFS, so
# even quiet TTS output triggers it).

Hook = Callable[[], Awaitable[None]]
ProgressHook = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class ChunkRef:
    """One voiced chunk, as the TTS stage's manifest lists it, plus what its line is about."""

    path: Path
    segment: int
    kind: str
    item_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MixOptions:
    target_lufs: float = -16.0
    bitrate_kbps: int = 128
    channels: int = 1
    segment_gap_ms: int = 400
    transition_gap_ms: int = 900
    music_volume_db: float = -22.0


@dataclass(frozen=True)
class MixResult:
    path: Path
    duration_s: float
    size_bytes: int
    # What the speech measured before normalisation; None when it was silent.
    input_lufs: float | None


def gap_before(previous: ChunkRef, current: ChunkRef, options: MixOptions) -> int:
    """The pause between two chunks: tiny inside a line, short between lines, long between stories.

    A new story starts when a `story` line follows something that was not the same story, and a
    transition or the outro is always set apart from what came before.
    """
    if previous.segment == current.segment:
        return CHUNK_GAP_MS
    story_change = (
        current.kind in ("transition", "outro")
        or previous.kind == "transition"
        or (
            current.kind == "story"
            and (previous.kind != "story" or previous.item_ids != current.item_ids)
        )
    )
    return options.transition_gap_ms if story_change else options.segment_gap_ms


def _check_chunks(chunks: Sequence[ChunkRef]) -> None:
    """The TTS stage promises 24 kHz mono 16-bit WAV. The concat-by-copy below does not look
    inside files, so a damaged or different chunk would silently ruin the episode: check."""
    for chunk in chunks:
        try:
            with wave.open(str(chunk.path), "rb") as wav:
                format_ok = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (
                    1, 2, SPEECH_RATE,
                )  # fmt: skip
        except (wave.Error, EOFError, OSError) as exc:
            raise FFmpegError(f"{chunk.path.name} is not valid audio ({exc})") from exc
        if not format_ok:
            raise FFmpegError(f"{chunk.path.name} is not 24 kHz mono 16-bit audio")


def _write_silence(path: Path, milliseconds: int) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SPEECH_RATE)
        out.writeframes(b"\x00\x00" * (SPEECH_RATE * milliseconds // 1000))


def _quote(path: Path) -> str:
    return "'" + str(path).replace("'", "'\\''") + "'"


async def build_speech(chunks: Sequence[ChunkRef], work: Path, options: MixOptions) -> Path:
    """One WAV of all the chunks in order with the right pauses between them.

    The chunks and the silences are in the same format, so ffmpeg's concat demuxer can join them
    by copying, which is fast and keeps memory flat however long the episode is.
    """
    await anyio.to_thread.run_sync(_check_chunks, chunks)
    gaps = anyio.Path(work / "gaps")
    await gaps.mkdir(parents=True, exist_ok=True)
    entries: list[Path] = []
    made: set[int] = set()
    previous: ChunkRef | None = None
    for chunk in chunks:
        if previous is not None:
            ms = gap_before(previous, chunk, options)
            silence = work / "gaps" / f"{ms}.wav"
            if ms and ms not in made:
                await anyio.to_thread.run_sync(_write_silence, silence, ms)
                made.add(ms)
            if ms:
                entries.append(silence)
        entries.append(chunk.path)
        previous = chunk
    listing = work / "speech.txt"
    await anyio.Path(listing).write_text("".join(f"file {_quote(p)}\n" for p in entries))
    speech = work / "speech.wav"
    await run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(speech)])
    return speech


async def add_music_bed(speech: Path, music: Path, work: Path, options: MixOptions) -> Path:
    """Loop `music` under the speech, quiet and pushed further down whenever someone talks."""
    length = await duration_of(speech)
    fade_out_at = max(0.0, length - MUSIC_FADE_S)
    graph = (
        f"[1:a]aresample={SPEECH_RATE},aformat=sample_fmts=fltp:channel_layouts=mono,"
        f"atrim=0:{length:.3f},volume={options.music_volume_db}dB,"
        f"afade=t=in:d={MUSIC_FADE_S},afade=t=out:st={fade_out_at:.3f}:d={MUSIC_FADE_S}[bed];"
        "[0:a]aformat=sample_fmts=fltp:channel_layouts=mono,asplit=2[voice][key];"
        "[bed][key]sidechaincompress=threshold=0.01:ratio=10:attack=30:release=500[ducked];"
        "[voice][ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[out]"
    )
    mixed = work / "speech-with-music.wav"
    await run_ffmpeg(
        [
            "-i",
            str(speech),
            "-stream_loop",
            "-1",
            "-i",
            str(music),
            "-filter_complex",
            graph,
            "-map",
            "[out]",
            "-t",
            f"{length:.3f}",
            "-ar",
            str(SPEECH_RATE),
            "-c:a",
            "pcm_s16le",
            str(mixed),
        ]  # fmt: skip
    )
    return mixed


def _layout(channels: int) -> str:
    return "mono" if channels == 1 else "stereo"


def _inputs_graph(parts: Sequence[Path], options: MixOptions) -> tuple[list[str], str]:
    """Input arguments, and the filter graph that makes them one signal in the output format."""
    args: list[str] = []
    for part in parts:
        args += ["-i", str(part)]
    prepared = "".join(
        f"[{i}:a]aresample={OUTPUT_RATE},"
        f"aformat=sample_fmts=fltp:channel_layouts={_layout(options.channels)}[p{i}];"
        for i in range(len(parts))
    )
    joined = "".join(f"[p{i}]" for i in range(len(parts)))
    return args, f"{prepared}{joined}concat=n={len(parts)}:v=0:a=1[cat]"


_MEASUREMENT = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.DOTALL)


def _parse_measurement(stderr: str) -> dict[str, str] | None:
    match = _MEASUREMENT.search(stderr)
    if not match:
        return None
    values: dict[str, str] = json.loads(match.group(0))
    if any(values.get(k, "-inf") in ("-inf", "inf", "nan") for k in ("input_i", "input_tp")):
        return None  # silence cannot be measured, and does not need to be normalised
    return values


async def render_mp3(
    parts: Sequence[Path],
    out: Path,
    options: MixOptions,
    *,
    progress: ProgressHook | None = None,
) -> MixResult:
    """Join `parts`, normalise the loudness (measure, then correct linearly) and encode MP3."""
    inputs, graph = _inputs_graph(parts, options)
    target = f"loudnorm=I={options.target_lufs}:TP={TRUE_PEAK_DB}:LRA={LOUDNESS_RANGE}"
    first = await run_ffmpeg(
        [
            *inputs,
            "-filter_complex",
            f"{graph};[cat]{target}:print_format=json[out]",
            "-map",
            "[out]",
            "-f",
            "null",
            "-",
        ]  # fmt: skip
    )
    if progress:
        await progress(0.5)
    measured = _parse_measurement(first)
    if measured is not None:
        second = (
            f"{target}:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
            f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
            f":offset={measured['target_offset']}:linear=true,aresample={OUTPUT_RATE}"
        )
    else:
        second = f"aresample={OUTPUT_RATE}"
    await run_ffmpeg(
        [
            *inputs,
            "-filter_complex",
            f"{graph};[cat]{second}[out]",
            "-map",
            "[out]",
            "-c:a",
            "libmp3lame",
            "-b:a",
            f"{options.bitrate_kbps}k",
            "-ar",
            str(OUTPUT_RATE),
            "-ac",
            str(options.channels),
            "-write_xing",
            "1",
            str(out),
        ]  # fmt: skip
    )
    stat = await anyio.Path(out).stat()
    return MixResult(
        path=out,
        duration_s=await duration_of(out),
        size_bytes=stat.st_size,
        input_lufs=float(measured["input_i"]) if measured else None,
    )


async def mix_episode(
    chunks: Sequence[ChunkRef],
    work: Path,
    out: Path,
    options: MixOptions,
    *,
    intro: Path | None = None,
    outro: Path | None = None,
    music: Path | None = None,
    checkpoint: Hook | None = None,
    progress: ProgressHook | None = None,
) -> MixResult:
    """The episode: [intro] speech (over an optional music bed) [outro], at the target loudness."""

    async def step(fraction: float) -> None:
        if checkpoint:
            await checkpoint()
        if progress:
            await progress(fraction)

    await step(0.0)
    body = await build_speech(chunks, work, options)
    await step(0.25)
    if music is not None:
        body = await add_music_bed(body, music, work, options)
    await step(0.5)
    parts = [p for p in (intro, body, outro) if p is not None]

    async def second_half(fraction: float) -> None:
        if progress:
            await progress(0.5 + 0.5 * fraction)

    result = await render_mp3(parts, out, options, progress=second_half)
    await step(1.0)
    return result
