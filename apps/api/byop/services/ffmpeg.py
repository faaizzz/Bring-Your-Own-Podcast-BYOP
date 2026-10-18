"""Running ffmpeg and ffprobe as subprocesses. Audio goes through files, never through memory."""

import asyncio
import re
from collections.abc import Sequence
from pathlib import Path

DEFAULT_TIMEOUT_S = 900.0


class FFmpegError(Exception):
    """ffmpeg or ffprobe failed; the message is the useful end of its error output."""


def _tail(stderr: bytes) -> str:
    lines = [line.strip() for line in stderr.decode(errors="replace").splitlines() if line.strip()]
    errors = [
        line for line in lines if re.search(r"error|invalid|failed|no such|not found", line, re.I)
    ]
    return " | ".join((errors or lines)[-3:]) or "no error output"


async def _run(command: Sequence[str], timeout_s: float) -> tuple[bytes, bytes]:
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise FFmpegError(f"{command[0]} is not installed") from exc
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout_s)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise FFmpegError(f"{command[0]} timed out after {timeout_s:.0f} seconds") from exc
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise
    if process.returncode != 0:
        raise FFmpegError(f"{command[0]} failed: {_tail(stderr)}")
    return stdout, stderr


async def run_ffmpeg(args: Sequence[str], *, timeout_s: float = DEFAULT_TIMEOUT_S) -> str:
    """Run `ffmpeg -hide_banner -nostdin -y <args>`; returns what it printed on stderr."""
    _out, err = await _run(["ffmpeg", "-hide_banner", "-nostdin", "-y", *args], timeout_s)
    return err.decode(errors="replace")


async def probe(path: Path, *, timeout_s: float = 60.0) -> tuple[float, bool]:
    """(duration in seconds, whether the file has an audio stream) of any media file."""
    out, _err = await _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type",
            "-of",
            "csv=p=0",
            str(path),
        ],  # fmt: skip
        timeout_s,
    )
    lines = out.decode().split()
    has_audio = any(line.startswith("audio") for line in lines)
    durations = [line for line in lines if re.fullmatch(r"\d+(\.\d+)?", line)]
    return (float(durations[-1]) if durations else 0.0), has_audio


async def duration_of(path: Path) -> float:
    return (await probe(path))[0]
