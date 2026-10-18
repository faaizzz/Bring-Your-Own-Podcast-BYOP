"""Normalise whatever a provider returns to one canonical format: WAV, 24 kHz, mono, 16-bit."""

import asyncio
import wave
from dataclasses import dataclass
from pathlib import Path

from byop.providers.tts.errors import AudioConversionError

CANONICAL_SAMPLE_RATE = 24000
FFMPEG_TIMEOUT_SECONDS = 120
_COPY_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class AudioFormat:
    """One output format a provider can return."""

    name: str  # our name: "pcm" or "mp3"
    extension: str  # of the temporary file
    api_value: str  # what the provider's API calls it
    # Raw signed 16-bit little-endian mono PCM at this rate; None for encoded audio (mp3, opus).
    pcm_rate: int | None = None


def _wrap_pcm(source: Path, destination: Path, rate: int) -> None:
    size = source.stat().st_size
    if size % 2:
        raise AudioConversionError("PCM audio has an odd number of bytes")
    with source.open("rb") as raw, wave.open(str(destination), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        while chunk := raw.read(_COPY_CHUNK):
            out.writeframes(chunk)


async def to_canonical_wav(source: Path, audio_format: AudioFormat, destination: Path) -> None:
    """Write `source` (in `audio_format`) to `destination` as canonical WAV."""
    if audio_format.pcm_rate == CANONICAL_SAMPLE_RATE:
        # Already the right samples: only a header is needed, no ffmpeg.
        await asyncio.to_thread(_wrap_pcm, source, destination, CANONICAL_SAMPLE_RATE)
        return

    input_options: list[str] = []
    if audio_format.pcm_rate is not None:
        input_options = ["-f", "s16le", "-ar", str(audio_format.pcm_rate), "-ac", "1"]
    command = [
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
        *input_options,
        "-i", str(source),
        "-ar", str(CANONICAL_SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le",
        str(destination),
    ]  # fmt: skip
    await _run_ffmpeg(command)


async def wav_to_mp3(source: Path, destination: Path) -> None:
    """Encode `source` as a small mono MP3, good enough for voice previews."""
    command = [
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
        "-i", str(source),
        "-ac", "1", "-c:a", "libmp3lame", "-b:a", "64k",
        str(destination),
    ]  # fmt: skip
    await _run_ffmpeg(command)


async def _run_ffmpeg(command: list[str]) -> None:
    try:
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError as exc:
        raise AudioConversionError("ffmpeg is not installed") from exc
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), FFMPEG_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        process.kill()
        raise AudioConversionError("ffmpeg timed out converting audio") from exc
    if process.returncode != 0:
        detail = stderr.decode(errors="replace").strip().splitlines()[-1:]  # last line only
        raise AudioConversionError(f"ffmpeg could not convert the audio: {' '.join(detail)}")
