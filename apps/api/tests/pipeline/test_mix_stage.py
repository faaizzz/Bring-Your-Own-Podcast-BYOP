import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings
from byop.models import Episode, Run, Show, User
from byop.models.enums import EpisodeStatus, RunStatus
from byop.pipeline.orchestrator import Stage, StageResult, run_stage
from byop.pipeline.stages import mix as mix_stage
from byop.pipeline.workdir import work_dir
from byop.services import audio_mix
from byop.services import runs as run_service
from byop.services.audio_mix import MixResult
from byop.storage import LocalStorage, StorageError
from tests.audio.helpers import lufs, stream_info, tone
from tests.helpers import make_settings
from tests.models.factories import make_show

STAGES = [Stage("mix", mix_stage.run, 85, 95)]


def settings(tmp_path: Path, **overrides: object) -> Settings:
    return make_settings(media_root=str(tmp_path), **overrides)


async def prepare(
    session: AsyncSession,
    user: User,
    tmp_path: Path,
    *,
    manifest: bool = True,
    episode: bool = True,
) -> tuple[Show, Run]:
    """A run whose speech has been voiced: four one-second tone chunks and their manifest."""
    show = await make_show(session, user)
    run = await run_service.create_run(session, user.id, show.id)
    script = {
        "segments": [
            {"speaker": "Alex", "text": "Welcome", "kind": "intro", "item_ids": []},
            {"speaker": "Sam", "text": "Story one", "kind": "story", "item_ids": ["a"]},
            {"speaker": "Alex", "text": "Story two", "kind": "story", "item_ids": ["b"]},
            {"speaker": "Sam", "text": "Bye", "kind": "outro", "item_ids": []},
        ]
    }
    if episode:
        session.add(
            Episode(
                user_id=user.id, show_id=show.id, run_id=run.id, title="Ep",
                status=EpisodeStatus.DRAFT, script=script,
            )
        )  # fmt: skip
    await session.flush()
    if manifest:
        tts = work_dir(tmp_path, run.id) / "tts"
        tts.mkdir(parents=True)
        chunks = []
        for index, segment in enumerate(script["segments"]):
            tone(tts / f"{index:05d}-0.wav", 1.0, level_db=-14 - index)
            chunks.append(
                {
                    "index": index, "segment": index, "kind": segment["kind"],
                    "speaker": segment["speaker"], "files": [f"tts/{index:05d}-0.wav"],
                    "provider": "kokoro", "voice_id": "af_bella", "characters": 8,
                    "cost_usd": None, "latency_ms": 10, "fallback": False,
                }
            )  # fmt: skip
        manifest_file = work_dir(tmp_path, run.id) / "manifest.json"
        manifest_file.write_text(json.dumps({"version": 1, "chunks": chunks}))
    return show, run


async def go(session: AsyncSession, run: Run, cfg: Settings) -> StageResult:
    return await run_stage(session, cfg, run.id, "mix", stages=STAGES)


async def episode_of(session: AsyncSession, run: Run) -> Episode:
    episode = await session.scalar(select(Episode).where(Episode.run_id == run.id))
    assert episode is not None
    await session.refresh(episode)
    return episode


# 4 s of speech + 0.9 (intro->story) + 0.9 (story->story) + 0.9 (->outro)
SPEECH_S = 6.7


async def test_the_episode_audio_is_mixed_stored_and_recorded(
    db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    show, run = await prepare(db_session, admin_user, tmp_path)

    assert await go(db_session, run, settings(tmp_path)) is StageResult.DONE

    episode = await episode_of(db_session, run)
    assert episode.audio_key == f"shows/{show.id}/episodes/{episode.id}/audio.mp3"
    stored = tmp_path / episode.audio_key
    assert stored.is_file() and episode.size_bytes == stored.stat().st_size
    assert episode.duration_s == pytest.approx(SPEECH_S, abs=0.5)
    assert lufs(stored) == pytest.approx(-16.0, abs=0.7)
    assert stream_info(stored)["codec_name"] == "mp3"
    await db_session.refresh(run, ["events"])
    ready = next(e for e in run.events if e.message.startswith("Episode audio ready"))
    assert ready.data is not None and ready.data["music"] is False and ready.data["intro"] is False
    assert run.progress == 95


async def test_the_shows_intro_outro_and_music_bed_are_used(
    db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    show, run = await prepare(db_session, admin_user, tmp_path)
    storage = LocalStorage(tmp_path)
    assets = tmp_path / "upload"
    assets.mkdir()
    await storage.put_file(
        f"shows/{show.id}/audio/intro.wav", tone(assets / "i.wav", 1.5, 880, rate=44100)
    )
    await storage.put_file(
        f"shows/{show.id}/audio/outro.mp3", tone(assets / "o.mp3", 2.0, 660, rate=44100)
    )
    await storage.put_file(
        f"shows/{show.id}/audio/music.wav", tone(assets / "m.wav", 2.0, 220, -8, rate=44100)
    )
    show.intro_key = f"shows/{show.id}/audio/intro.wav"
    show.outro_key = f"shows/{show.id}/audio/outro.mp3"
    show.music_key = f"shows/{show.id}/audio/music.wav"
    await db_session.flush()

    assert await go(db_session, run, settings(tmp_path)) is StageResult.DONE

    episode = await episode_of(db_session, run)
    assert episode.duration_s == pytest.approx(SPEECH_S + 3.5, abs=0.5)
    await db_session.refresh(run, ["events"])
    ready = next(e for e in run.events if e.message.startswith("Episode audio ready"))
    assert ready.data is not None and (
        ready.data["intro"],
        ready.data["outro"],
        ready.data["music"],
    ) == (True, True, True)
    assert any("with intro, outro and a music bed" in e.message for e in run.events)


async def test_a_clip_that_is_gone_from_storage_is_skipped_not_fatal(
    db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    show, run = await prepare(db_session, admin_user, tmp_path)
    show.intro_key = f"shows/{show.id}/audio/intro.wav"  # nothing is stored there
    await db_session.flush()

    assert await go(db_session, run, settings(tmp_path)) is StageResult.DONE
    assert (await episode_of(db_session, run)).duration_s == pytest.approx(SPEECH_S, abs=0.5)


async def test_the_mix_follows_the_configured_format(
    db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    _show, run = await prepare(db_session, admin_user, tmp_path)

    await go(
        db_session,
        run,
        settings(tmp_path, audio_channels=2, audio_bitrate_kbps=96, audio_target_lufs=-18.0),
    )

    episode = await episode_of(db_session, run)
    assert episode.audio_key is not None
    info = stream_info(tmp_path / episode.audio_key)
    assert info["channels"] == 2 and abs(int(info["bit_rate"]) - 96_000) < 4_000
    assert lufs(tmp_path / episode.audio_key) == pytest.approx(-18.0, abs=0.7)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"manifest": False}, "There is no voiced audio to mix."),
        ({"episode": False}, "There is no episode to put the audio on."),
    ],
)
async def test_missing_inputs_fail_the_run_clearly(
    kwargs: dict[str, bool],
    message: str,
    db_session: AsyncSession,
    admin_user: User,
    tmp_path: Path,
) -> None:
    _show, run = await prepare(db_session, admin_user, tmp_path, **kwargs)

    assert await go(db_session, run, settings(tmp_path)) is StageResult.FAILED
    await db_session.refresh(run)
    assert run.error == message


async def test_an_unreadable_chunk_fails_the_run_with_ffmpegs_reason(
    db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    _show, run = await prepare(db_session, admin_user, tmp_path)
    (work_dir(tmp_path, run.id) / "tts" / "00001-0.wav").write_bytes(b"not audio at all")

    assert await go(db_session, run, settings(tmp_path)) is StageResult.FAILED

    await db_session.refresh(run)
    assert run.error is not None and run.error.startswith(
        "Mixing the audio failed: 00001-0.wav is not valid"
    )
    assert not work_dir(tmp_path, run.id).exists()  # a failed run leaves no scratch files


async def test_a_storage_problem_is_retried_not_fatal(
    db_session: AsyncSession, admin_user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _show, run = await prepare(db_session, admin_user, tmp_path)

    class Broken(LocalStorage):
        async def put_file(self, key: str, path: Path, *, content_type: str | None = None) -> None:
            raise StorageError("bucket unreachable")

    monkeypatch.setattr(mix_stage, "build_storage", lambda s: Broken(tmp_path))

    from byop.pipeline.errors import TransientStageError

    with pytest.raises(TransientStageError, match="bucket unreachable"):
        await go(db_session, run, settings(tmp_path))

    await db_session.refresh(run)
    assert run.status is RunStatus.RUNNING
    assert (work_dir(tmp_path, run.id) / "manifest.json").exists()  # a retry can start over


async def test_cancelling_during_the_mix_stops_it_and_cleans_up(
    db_session: AsyncSession, admin_user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _show, run = await prepare(db_session, admin_user, tmp_path)
    real = audio_mix.mix_episode

    async def cancel_then_mix(*args: Any, **kwargs: Any) -> MixResult:  # noqa: ANN401 - forwards
        await db_session.execute(update(Run).where(Run.id == run.id).values(cancel_requested=True))
        await db_session.commit()
        return await real(*args, **kwargs)

    monkeypatch.setattr("byop.pipeline.stages.mix.mix_episode", cancel_then_mix)

    assert await go(db_session, run, settings(tmp_path)) is StageResult.CANCELLED

    episode = await episode_of(db_session, run)
    assert episode.audio_key is None
    assert not work_dir(tmp_path, run.id).exists()
    assert not (tmp_path / "shows").exists()  # nothing was uploaded
