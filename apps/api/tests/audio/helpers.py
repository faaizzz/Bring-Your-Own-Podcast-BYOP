"""Tiny generated clips and ffmpeg-based measurements, for checking real mixes."""

import json
import math
import re
import subprocess
from pathlib import Path

SINE_PEAK_DB = 20 * math.log10(0.125)  # what ffmpeg's `sine` source produces: -18.06 dBFS


def ffmpeg(*args: str) -> str:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-y", *args], capture_output=True, check=True
    )
    return result.stderr.decode()


def tone(
    path: Path, seconds: float, freq: int = 440, level_db: float = -12.0, rate: int = 24000
) -> Path:
    """A sine wave with the given peak level (dBFS); the codec follows the file suffix."""
    codec = ["-c:a", "pcm_s16le"] if path.suffix == ".wav" else []
    ffmpeg(
        "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}:sample_rate={rate}",
        "-af", f"volume={level_db - SINE_PEAK_DB:.2f}dB", *codec, "-ac", "1", str(path),
    )  # fmt: skip
    return path


def silence(path: Path, seconds: float, rate: int = 24000) -> Path:
    ffmpeg(
        "-f", "lavfi", "-i", f"anullsrc=r={rate}:cl=mono", "-t", str(seconds),
        "-c:a", "pcm_s16le", str(path),
    )  # fmt: skip
    return path


def lufs(path: Path) -> float:
    """Integrated loudness (EBU R128) of a file."""
    err = ffmpeg("-i", str(path), "-af", "ebur128=framelog=quiet", "-f", "null", "-")
    summary = err[err.rindex("Integrated loudness") :]
    return float(re.search(r"I:\s+(-?\d+(\.\d+)?) LUFS", summary).group(1))  # type: ignore[union-attr]


def stream_info(path: Path) -> dict[str, str | int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=codec_name,sample_rate,channels,bit_rate:format=duration,bit_rate",
         "-of", "json", str(path)],
        capture_output=True, check=True,
    )  # fmt: skip
    data = json.loads(out.stdout)
    return {**data["streams"][0], "duration": data["format"]["duration"]}


def level_db(path: Path, start: float, length: float, freq: int | None = None) -> float:
    """Peak level (dB) in a time window, optionally only around one frequency."""
    band = f"bandpass=f={freq}:width_type=h:w=30," if freq else ""
    err = ffmpeg(
        "-ss", str(start), "-t", str(length), "-i", str(path),
        "-af", f"{band}volumedetect", "-f", "null", "-",
    )  # fmt: skip
    match = re.search(r"max_volume: (-?\d+(\.\d+)?|-inf) dB", err)
    assert match is not None, err
    return float("-inf") if match.group(1) == "-inf" else float(match.group(1))
