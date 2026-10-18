import asyncio
from pathlib import Path

import pytest

from byop.providers.tts.audio import AudioFormat, to_canonical_wav
from byop.providers.tts.errors import AudioConversionError
from tests.providers.tts.helpers import mp3_bytes, pcm_bytes, read_wav


async def test_pcm_at_other_sample_rates_is_resampled_with_ffmpeg(tmp_path: Path) -> None:
    source = tmp_path / "in.pcm"
    source.write_bytes(pcm_bytes(16000))  # one second at 16 kHz
    destination = tmp_path / "out.wav"

    await to_canonical_wav(
        source, AudioFormat("pcm16", "pcm", "pcm_16000", pcm_rate=16000), destination
    )

    wav = read_wav(destination)
    assert (wav.channels, wav.sample_width, wav.rate) == (1, 2, 24000)
    assert abs(wav.frames - 24000) < 50


async def test_opus_like_encoded_audio_goes_through_ffmpeg(tmp_path: Path) -> None:
    source = tmp_path / "in.mp3"
    source.write_bytes(mp3_bytes(seconds=1.0, rate=22050, channels=1))
    destination = tmp_path / "out.wav"

    await to_canonical_wav(source, AudioFormat("mp3", "mp3", "mp3"), destination)

    wav = read_wav(destination)
    assert (wav.channels, wav.rate) == (1, 24000)
    assert abs(wav.frames - 24000) < 2500


async def test_missing_ffmpeg_is_a_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_ffmpeg(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_ffmpeg)
    source = tmp_path / "in.mp3"
    source.write_bytes(mp3_bytes())

    with pytest.raises(AudioConversionError, match="ffmpeg is not installed"):
        await to_canonical_wav(source, AudioFormat("mp3", "mp3", "mp3"), tmp_path / "out.wav")


async def test_pcm_at_24khz_needs_no_ffmpeg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("ffmpeg must not run for 24 kHz PCM")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    source = tmp_path / "in.pcm"
    source.write_bytes(pcm_bytes(480))

    await to_canonical_wav(
        source, AudioFormat("pcm", "pcm", "pcm", pcm_rate=24000), tmp_path / "out.wav"
    )

    assert read_wav(tmp_path / "out.wav").frames == 480
