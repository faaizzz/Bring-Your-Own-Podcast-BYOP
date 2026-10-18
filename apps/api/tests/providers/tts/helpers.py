import json
import subprocess
import wave
from array import array
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx
import respx

from byop.providers.common import RetryPolicy

FAST_RETRY = RetryPolicy(max_attempts=3, initial_wait_s=0.0, max_wait_s=0.0)


def pcm_bytes(samples: int = 2400) -> bytes:
    """Deterministic signed 16-bit little-endian mono samples (a sawtooth)."""
    data = array("h", [(i * 37) % 2000 - 1000 for i in range(samples)])
    return data.tobytes()


@lru_cache
def mp3_bytes(seconds: float = 0.5, rate: int = 44100, channels: int = 2) -> bytes:
    """A real MP3 (stereo, 44.1 kHz by default) generated with ffmpeg."""
    result = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-loglevel", "error",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-ar", str(rate), "-ac", str(channels), "-f", "mp3", "-",
        ],
        capture_output=True,
        check=True,
    )  # fmt: skip
    return result.stdout


@dataclass(frozen=True)
class WavInfo:
    channels: int
    sample_width: int
    rate: int
    frames: int
    data: bytes


def read_wav(path: Path) -> WavInfo:
    with wave.open(str(path), "rb") as wav:
        return WavInfo(
            wav.getnchannels(),
            wav.getsampwidth(),
            wav.getframerate(),
            wav.getnframes(),
            wav.readframes(wav.getnframes()),
        )


def json_body(route: respx.Route, call: int = -1) -> dict[str, object]:
    request: httpx.Request = route.calls[call].request
    return json.loads(request.content)  # type: ignore[no-any-return]
