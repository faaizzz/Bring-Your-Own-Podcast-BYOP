from pathlib import Path

import pytest

from byop.services.audio_mix import ChunkRef, MixOptions, gap_before, mix_episode
from byop.services.ffmpeg import FFmpegError
from tests.audio.helpers import level_db, lufs, silence, stream_info, tone

OPTIONS = MixOptions()  # -16 LUFS, 128 kbps mono, gaps 400 / 900 ms


def script_chunks(directory: Path) -> list[ChunkRef]:
    """intro | story A (two chunks) | story B | outro, each chunk a one-second tone."""
    paths = [tone(directory / f"c{i}.wav", 1.0, level_db=-18 + 4 * (i % 3)) for i in range(5)]
    return [
        ChunkRef(paths[0], 0, "intro"),
        ChunkRef(paths[1], 1, "story", ("a",)),
        ChunkRef(paths[2], 1, "story", ("a",)),  # same line: a tiny pause only
        ChunkRef(paths[3], 2, "story", ("b",)),
        ChunkRef(paths[4], 3, "outro"),
    ]


# 5 s of speech + 0.9 (intro->story) + 0.1 (same line) + 0.9 (story A->B) + 0.9 (->outro)
EXPECTED_SPEECH_S = 7.8


async def mix(
    tmp_path: Path,
    options: MixOptions = OPTIONS,
    *,
    intro: Path | None = None,
    outro: Path | None = None,
    music: Path | None = None,
) -> tuple[Path, float]:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    chunks = script_chunks(work)
    result = await mix_episode(
        chunks, work, tmp_path / "episode.mp3", options, intro=intro, outro=outro, music=music
    )
    assert result.path.exists() and result.size_bytes == result.path.stat().st_size
    return result.path, result.duration_s


# --- the golden tests ------------------------------------------------------------------------


async def test_a_plain_episode_has_the_right_length_and_loudness(tmp_path: Path) -> None:
    out, duration = await mix(tmp_path)

    assert duration == pytest.approx(EXPECTED_SPEECH_S, abs=0.2)
    assert lufs(out) == pytest.approx(-16.0, abs=0.7)


async def test_the_file_is_a_128k_mono_mp3_at_44_1_khz(tmp_path: Path) -> None:
    out, _ = await mix(tmp_path)

    info = stream_info(out)
    assert info["codec_name"] == "mp3"
    assert info["sample_rate"] == "44100" and info["channels"] == 1
    assert abs(int(info["bit_rate"]) - 128_000) < 4_000


async def test_the_bitrate_channels_and_loudness_target_are_configurable(tmp_path: Path) -> None:
    options = MixOptions(target_lufs=-19.0, bitrate_kbps=64, channels=2)

    out, duration = await mix(tmp_path, options)

    info = stream_info(out)
    assert info["channels"] == 2 and abs(int(info["bit_rate"]) - 64_000) < 4_000
    assert lufs(out) == pytest.approx(-19.0, abs=0.7)
    assert duration == pytest.approx(EXPECTED_SPEECH_S, abs=0.2)


async def test_quiet_and_loud_sources_end_up_at_the_same_loudness(tmp_path: Path) -> None:
    quiet_dir, loud_dir = tmp_path / "q", tmp_path / "l"
    results = []
    for directory, level in ((quiet_dir, -40.0), (loud_dir, -6.0)):
        directory.mkdir()
        chunk = ChunkRef(tone(directory / "c.wav", 2.0, level_db=level), 0, "story")
        work = directory / "work"
        work.mkdir()
        results.append(await mix_episode([chunk], work, directory / "out.mp3", OPTIONS))

    assert lufs(results[0].path) == pytest.approx(lufs(results[1].path), abs=0.7)
    assert lufs(results[0].path) == pytest.approx(-16.0, abs=0.7)
    assert results[0].input_lufs is not None and results[1].input_lufs is not None
    assert results[1].input_lufs - results[0].input_lufs == pytest.approx(34.0, abs=1.5)


async def test_intro_and_outro_clips_are_added_around_the_speech(tmp_path: Path) -> None:
    intro = tone(tmp_path / "intro.wav", 1.5, freq=880, rate=44100)
    outro = tone(tmp_path / "outro.mp3", 2.0, freq=660, rate=48000)

    out, duration = await mix(tmp_path, intro=intro, outro=outro)

    assert duration == pytest.approx(EXPECTED_SPEECH_S + 3.5, abs=0.25)
    assert lufs(out) == pytest.approx(-16.0, abs=0.7)
    jingle, speech = level_db(out, 0.2, 1.0, freq=880), level_db(out, 0.2, 1.0, freq=440)
    assert jingle - speech > 20  # the jingle plays first, the speech has not started yet
    assert level_db(out, 1.8, 0.2, freq=440) > level_db(out, 1.8, 0.2, freq=880) + 20


async def test_a_music_bed_is_heard_in_the_pauses_and_ducked_under_speech(tmp_path: Path) -> None:
    music = tone(tmp_path / "bed.wav", 3.0, freq=220, level_db=-6.0, rate=44100)

    out, duration = await mix(tmp_path, MixOptions(music_volume_db=-12.0), music=music)

    assert duration == pytest.approx(EXPECTED_SPEECH_S, abs=0.2)  # the bed adds no length
    assert lufs(out) == pytest.approx(-16.0, abs=0.7)
    in_pause = level_db(out, 1.5, 0.3, freq=220)  # late in the 0.9 s pause after the intro
    under_speech = level_db(out, 2.3, 0.3, freq=220)  # while someone is talking
    assert in_pause > -45  # the bed is there ...
    assert in_pause - under_speech > 6  # ... and drops by more than 6 dB under the voice
    assert (
        level_db(out, 0.0, 0.05, freq=220) < in_pause - 6
    )  # it fades in rather than starting loud


async def test_without_music_the_pauses_are_silent(tmp_path: Path) -> None:
    out, _ = await mix(tmp_path)

    assert level_db(out, 1.2, 0.5) < -60  # the pause after the intro is digital silence


async def test_a_short_bed_is_looped_to_cover_the_whole_episode(tmp_path: Path) -> None:
    music = tone(tmp_path / "bed.wav", 1.0, freq=220, level_db=-6.0, rate=44100)

    out, duration = await mix(tmp_path, MixOptions(music_volume_db=-12.0), music=music)

    assert duration == pytest.approx(EXPECTED_SPEECH_S, abs=0.2)
    assert level_db(out, 4.2, 0.5, freq=220) > -45  # in the pause after story A, 4 s into a 1 s bed


async def test_the_bed_can_be_in_any_format_and_channel_layout(tmp_path: Path) -> None:
    from tests.audio.helpers import ffmpeg

    music = tmp_path / "bed.mp3"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=330:duration=2", "-ac", "2", str(music))

    out, duration = await mix(tmp_path, music=music)

    assert duration == pytest.approx(EXPECTED_SPEECH_S, abs=0.2) and out.exists()


async def test_silent_speech_does_not_break_normalisation(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    chunk = ChunkRef(silence(work / "s.wav", 1.0), 0, "story")

    result = await mix_episode([chunk], work, tmp_path / "out.mp3", OPTIONS)

    assert result.input_lufs is None and result.duration_s == pytest.approx(1.0, abs=0.2)


# --- pauses between chunks ------------------------------------------------------------------


def ref(segment: int, kind: str, *ids: str) -> ChunkRef:
    return ChunkRef(Path("x.wav"), segment, kind, ids)


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        (ref(1, "story", "a"), ref(1, "story", "a"), 100),  # the next chunk of the same line
        (ref(0, "intro"), ref(1, "story", "a"), 900),  # the first story starts
        (ref(1, "story", "a"), ref(2, "story", "a"), 400),  # the same story goes on, another voice
        (ref(1, "story", "a"), ref(2, "story", "b"), 900),  # a new story
        (ref(1, "story", "a"), ref(2, "transition"), 900),
        (ref(2, "transition"), ref(3, "story", "b"), 900),
        (ref(3, "story", "b"), ref(4, "outro"), 900),
        (ref(0, "intro"), ref(1, "intro"), 400),  # two voices share the welcome
    ],
)
def test_the_pause_between_chunks(previous: ChunkRef, current: ChunkRef, expected: int) -> None:
    assert gap_before(previous, current, OPTIONS) == expected


def test_the_pauses_are_configurable() -> None:
    options = MixOptions(segment_gap_ms=250, transition_gap_ms=1500)

    assert gap_before(ref(1, "story", "a"), ref(2, "story", "a"), options) == 250
    assert gap_before(ref(1, "story", "a"), ref(2, "story", "b"), options) == 1500


# --- robustness ----------------------------------------------------------------------------------


async def test_a_corrupt_chunk_gives_a_clear_error_instead_of_garbage(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    good = tone(work / "good.wav", 1.0)
    bad = work / "bad.wav"
    bad.write_bytes(b"this is not audio")

    with pytest.raises(FFmpegError, match=r"bad\.wav is not valid audio"):
        await mix_episode(
            [ChunkRef(good, 0, "story"), ChunkRef(bad, 1, "story")],
            work, tmp_path / "out.mp3", OPTIONS,
        )  # fmt: skip

    assert not (tmp_path / "out.mp3").exists()


async def test_a_chunk_in_another_format_is_refused_too(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    wrong_rate = tone(work / "wrong.wav", 1.0, rate=44100)

    with pytest.raises(FFmpegError, match="not 24 kHz mono 16-bit"):
        await mix_episode([ChunkRef(wrong_rate, 0, "story")], work, tmp_path / "out.mp3", OPTIONS)


async def test_paths_with_quotes_and_spaces_are_fine(tmp_path: Path) -> None:
    odd = tmp_path / "it's a work dir"
    odd.mkdir()
    chunk = ChunkRef(tone(odd / "a chunk.wav", 0.5), 0, "story")

    result = await mix_episode([chunk], odd, tmp_path / "out.mp3", OPTIONS)

    assert result.duration_s == pytest.approx(0.5, abs=0.2)


async def test_the_mix_stops_between_steps_when_asked(tmp_path: Path) -> None:
    class Stop(Exception):
        pass

    calls = {"n": 0}

    async def checkpoint() -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise Stop

    work = tmp_path / "work"
    work.mkdir()

    with pytest.raises(Stop):
        await mix_episode(
            script_chunks(work), work, tmp_path / "out.mp3", OPTIONS, checkpoint=checkpoint
        )

    assert not (tmp_path / "out.mp3").exists()  # it never got to the encode


async def test_progress_runs_from_zero_to_one(tmp_path: Path) -> None:
    seen: list[float] = []

    async def progress(fraction: float) -> None:
        seen.append(fraction)

    work = tmp_path / "work"
    work.mkdir()
    await mix_episode(script_chunks(work), work, tmp_path / "out.mp3", OPTIONS, progress=progress)

    assert seen[0] == 0.0 and seen[-1] == 1.0 and seen == sorted(seen)
