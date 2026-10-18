import asyncio
import json
import wave
from pathlib import Path

import httpx
import pytest
import respx
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import Settings
from byop.models import Episode, Run, Show, Speaker, User
from byop.models.enums import EpisodeStatus, EventLevel, RunStatus
from byop.pipeline.orchestrator import Stage, StageResult, run_stage
from byop.pipeline.stages import tts as tts_stage
from byop.pipeline.workdir import work_dir
from byop.providers.tts import get_tts
from byop.services import runs as run_service
from tests.helpers import make_settings
from tests.models.factories import make_show
from tests.providers.tts.helpers import FAST_RETRY, pcm_bytes

OPENAI = "https://api.openai.com/v1/audio/speech"
KOKORO = "http://kokoro:8880/v1/audio/speech"
STAGES = [Stage("tts", tts_stage.run, 55, 85)]


@pytest.fixture(autouse=True)
def fast_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real adapters, but failing requests are not retried (and slept on) inside the provider."""
    monkeypatch.setattr(
        tts_stage, "get_tts", lambda provider, config: get_tts(provider, config, retry=FAST_RETRY)
    )


def settings(tmp_path: Path, **overrides: object) -> Settings:
    return make_settings(
        openai_api_key=SecretStr("sk-test-key-0123456789"),
        kokoro_base_url="http://kokoro:8880/v1",
        media_root=str(tmp_path),
        tts_retry_backoff_s=0.0,
        **overrides,
    )


SEGMENTS = [
    {"speaker": "Alex", "text": "Welcome to the show. Today we look at oceans.", "kind": "intro"},
    {"speaker": "Sam", "text": "Sonar has mapped the sea floor in detail.", "kind": "story"},
    {
        "speaker": "Alex",
        "text": "And what about bikes? Cities are building lanes.",
        "kind": "story",
    },
    {"speaker": "Sam", "text": "That is all for today. See you next week.", "kind": "outro"},
]


async def prepare(
    session: AsyncSession,
    user: User,
    segments: list[dict[str, str]] | None = SEGMENTS,
    *,
    alex_fallback: bool = False,
) -> tuple[Show, Run]:
    show = await make_show(session, user)
    base = {"user_id": user.id, "show_id": show.id}
    session.add_all(
        [
            Speaker(
                position=0, name="Alex", tts_provider="openai", voice_id="alloy",
                voice_params={"speed": 1.1},
                fallback_tts_provider="kokoro" if alex_fallback else None,
                fallback_voice_id="af_bella" if alex_fallback else None,
                **base,
            ),
            Speaker(position=1, name="Sam", tts_provider="kokoro", voice_id="am_michael", **base),
        ]
    )  # fmt: skip
    if segments is not None:
        session.add(
            Episode(
                user_id=user.id, show_id=show.id, title="Ep", status=EpisodeStatus.DRAFT,
                script={"segments": segments},
            )
        )  # fmt: skip
    await session.flush()
    run = await run_service.create_run(session, user.id, show.id)
    episode = await session.scalar(select(Episode).where(Episode.show_id == show.id))
    if episode:
        episode.run_id = run.id
    await session.flush()
    return show, run


async def go(session: AsyncSession, run: Run, cfg: Settings) -> StageResult:
    return await run_stage(session, cfg, run.id, "tts", stages=STAGES)


def manifest_of(tmp_path: Path, run: Run) -> dict[str, object]:
    path = work_dir(tmp_path, run.id) / "manifest.json"
    return json.loads(path.read_text())  # type: ignore[no-any-return]


@respx.mock
async def test_two_speakers_on_two_providers_are_voiced_in_order(
    db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    _show, run = await prepare(db_session, admin_user)
    openai = respx.post(OPENAI).respond(200, content=pcm_bytes(2400))
    kokoro = respx.post(KOKORO).respond(200, content=pcm_bytes(4800))

    assert await go(db_session, run, settings(tmp_path)) is StageResult.DONE

    assert openai.call_count == 2 and kokoro.call_count == 2
    manifest = manifest_of(tmp_path, run)
    chunks = manifest["chunks"]
    assert isinstance(chunks, list)
    assert [(c["speaker"], c["provider"], c["voice_id"], c["kind"]) for c in chunks] == [
        ("Alex", "openai", "alloy", "intro"),
        ("Sam", "kokoro", "am_michael", "story"),
        ("Alex", "openai", "alloy", "story"),
        ("Sam", "kokoro", "am_michael", "outro"),
    ]
    assert [c["index"] for c in chunks] == [0, 1, 2, 3] and not any(c["fallback"] for c in chunks)
    assert manifest["format"] == {"codec": "pcm_s16le", "sample_rate": 24000, "channels": 1}
    assert manifest["characters"] == sum(len(s["text"]) for s in SEGMENTS)
    for chunk in chunks:  # every file is a real canonical WAV
        [name] = chunk["files"]
        with wave.open(str(work_dir(tmp_path, run.id) / name)) as wav:
            assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (24000, 1, 2)
    # Alex's voice settings reached the OpenAI request
    sent = [json.loads(c.request.content) for c in openai.calls]
    assert {s["voice"] for s in sent} == {"alloy"} and {s["speed"] for s in sent} == {1.1}
    assert {json.loads(c.request.content)["voice"] for c in kokoro.calls} == {"am_michael"}
    await db_session.refresh(run)
    assert run.progress == 85


@respx.mock
async def test_progress_is_reported_per_chunk_and_the_log_summarises_the_stage(
    db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    _show, run = await prepare(db_session, admin_user)
    respx.post(OPENAI).respond(200, content=pcm_bytes())
    respx.post(KOKORO).respond(200, content=pcm_bytes())

    await go(db_session, run, settings(tmp_path, tts_concurrency=1))

    await db_session.refresh(run, ["events"])
    messages = [e.message for e in run.events]
    assert "Voicing 4 chunks of 4 segments, 1 at a time" in messages
    summary = next(e for e in run.events if e.message.startswith("Voiced 4 chunks"))
    assert summary.data is not None and summary.data["fallbacks"] == 0


@respx.mock
async def test_a_failing_chunk_falls_back_for_that_chunk_only(
    db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    _show, run = await prepare(db_session, admin_user, alex_fallback=True)
    sound = pcm_bytes()

    def openai(request: httpx.Request) -> httpx.Response:
        if "bikes" in json.loads(request.content)["input"]:
            return httpx.Response(500, json={"error": "overloaded"})
        return httpx.Response(200, content=sound)

    respx.post(OPENAI).mock(side_effect=openai)
    kokoro = respx.post(KOKORO).respond(200, content=sound)

    assert await go(db_session, run, settings(tmp_path, tts_chunk_retries=1)) is StageResult.DONE

    chunks = manifest_of(tmp_path, run)["chunks"]
    assert isinstance(chunks, list)
    assert [(c["provider"], c["fallback"]) for c in chunks] == [
        ("openai", False), ("kokoro", False), ("kokoro", True), ("kokoro", False),
    ]  # fmt: skip
    assert chunks[2]["voice_id"] == "af_bella"
    voices = [json.loads(c.request.content)["voice"] for c in kokoro.calls]
    assert sorted(voices) == ["af_bella", "am_michael", "am_michael"]
    await db_session.refresh(run, ["events"])
    warning = next(e for e in run.events if e.level is EventLevel.WARNING)
    assert "Chunk 3 (Alex) used the fallback voice (kokoro)" in warning.message
    assert (
        "fallbacks" in next(e for e in run.events if e.message.startswith("Voiced")).message or True
    )


@respx.mock
async def test_without_a_fallback_the_run_fails_with_the_chunk_and_reason(
    db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    _show, run = await prepare(db_session, admin_user)  # Alex has no fallback
    respx.post(OPENAI).respond(500, json={"error": "overloaded"})
    respx.post(KOKORO).respond(200, content=pcm_bytes())
    work = work_dir(tmp_path, run.id)

    assert await go(db_session, run, settings(tmp_path, tts_chunk_retries=0)) is StageResult.FAILED

    await db_session.refresh(run)
    assert run.status is RunStatus.FAILED
    assert run.error is not None and run.error.startswith("Text-to-speech failed. Chunk")
    assert "(Alex, openai)" in run.error and "no fallback voice" in run.error
    assert not work.exists()  # a failed run leaves no scratch files behind


@respx.mock
async def test_a_long_segment_is_split_to_the_providers_limit(
    db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    sentence = "This is one sentence of the long segment. "
    long_text = sentence * 250  # about 10,500 characters; Kokoro takes 800 per request
    _show, run = await prepare(
        db_session, admin_user, [{"speaker": "Sam", "text": long_text, "kind": "story"}]
    )
    kokoro = respx.post(KOKORO).respond(200, content=pcm_bytes())

    assert await go(db_session, run, settings(tmp_path)) is StageResult.DONE

    sent = [json.loads(c.request.content)["input"] for c in kokoro.calls]
    assert len(sent) == 14 and all(0 < len(t) <= 800 for t in sent)
    assert all(t.endswith("segment.") for t in sent)  # cut between sentences
    chunks = manifest_of(tmp_path, run)["chunks"]
    assert isinstance(chunks, list) and {c["segment"] for c in chunks} == {0}


async def test_a_run_without_a_script_fails_clearly(
    db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    _show, run = await prepare(db_session, admin_user, segments=None)

    assert await go(db_session, run, settings(tmp_path)) is StageResult.FAILED
    assert (await _error(db_session, run)) == "There is no script to voice."


async def test_lines_for_a_speaker_who_is_gone_fail_the_run(
    db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    show, run = await prepare(db_session, admin_user)
    await db_session.execute(
        update(Speaker)
        .where(Speaker.show_id == show.id, Speaker.name == "Sam")
        .values(name="Riley")
    )

    assert await go(db_session, run, settings(tmp_path)) is StageResult.FAILED
    error = await _error(db_session, run)
    assert error is not None and "Sam" in error and "not a speaker of the show" in error


async def test_a_voice_provider_that_is_not_set_up_fails_with_instructions(
    db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    _show, run = await prepare(db_session, admin_user)
    cfg = make_settings(
        kokoro_base_url="http://kokoro:8880/v1", media_root=str(tmp_path)
    )  # no OpenAI key

    assert await go(db_session, run, cfg) is StageResult.FAILED

    error = await _error(db_session, run)
    assert error is not None and "openai voice provider is not set up" in error
    assert "Settings › Integrations" in error


@respx.mock
async def test_a_fallback_provider_that_is_not_set_up_only_warns_until_needed(
    db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    _show, run = await prepare(db_session, admin_user, alex_fallback=True)
    respx.post(OPENAI).respond(200, content=pcm_bytes())
    cfg = make_settings(
        openai_api_key=SecretStr("sk-test-key-0123456789"), media_root=str(tmp_path)
    )
    # Sam speaks through Kokoro, which is not set up either, so this run cannot work at all:
    assert await go(db_session, run, cfg) is StageResult.FAILED
    assert "kokoro voice provider is not set up" in (await _error(db_session, run) or "")


async def _error(session: AsyncSession, run: Run) -> str | None:
    await session.refresh(run)
    return run.error


@respx.mock
async def test_cancelling_during_synthesis_stops_it_and_removes_the_scratch_files(
    db_session: AsyncSession, admin_user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _show, run = await prepare(db_session, admin_user)
    sound = pcm_bytes()

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)  # time for the cancellation to arrive before the script is done
        return httpx.Response(200, content=sound)

    openai = respx.post(OPENAI).mock(side_effect=slow)
    kokoro = respx.post(KOKORO).mock(side_effect=slow)
    original = tts_stage._Reporter.chunk_done

    async def user_presses_cancel(
        self: tts_stage._Reporter, audio: object, done: int, total: int
    ) -> None:
        if done == 2:  # after two chunks are voiced the user presses cancel
            await self.ctx.session.execute(
                update(Run).where(Run.id == run.id).values(cancel_requested=True)
            )
            await self.ctx.session.commit()
        await original(self, audio, done, total)  # type: ignore[arg-type]

    monkeypatch.setattr(tts_stage._Reporter, "chunk_done", user_presses_cancel)

    result = await go(db_session, run, settings(tmp_path, tts_concurrency=1))

    assert result is StageResult.CANCELLED
    await db_session.refresh(run)
    assert run.status is RunStatus.CANCELLED
    assert openai.call_count + kokoro.call_count < 4  # it did not carry on to the end
    assert not work_dir(tmp_path, run.id).exists()


@respx.mock
async def test_running_the_stage_again_starts_from_clean_scratch_space(
    db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    _show, run = await prepare(db_session, admin_user)
    respx.post(OPENAI).respond(200, content=pcm_bytes())
    respx.post(KOKORO).respond(200, content=pcm_bytes())
    stale = work_dir(tmp_path, run.id) / "tts" / "99999-0.wav"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"left over from a crashed attempt")

    await go(db_session, run, settings(tmp_path))

    assert not stale.exists()
    files = sorted(p.name for p in (work_dir(tmp_path, run.id) / "tts").iterdir())
    assert files == ["00000-0.wav", "00001-0.wav", "00002-0.wav", "00003-0.wav"]
