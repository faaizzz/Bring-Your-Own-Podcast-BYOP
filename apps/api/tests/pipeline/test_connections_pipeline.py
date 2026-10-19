"""A show whose model and voices both come from connections makes an episode end to end."""

import json
from pathlib import Path

import httpx
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Episode, Item, Speaker, UsageEvent, User
from byop.models.enums import UsageKind
from byop.pipeline.orchestrator import Stage, StageResult, run_stage
from byop.pipeline.stages import script as script_stage
from byop.pipeline.stages import tts as tts_stage
from byop.pipeline.workdir import work_dir
from byop.services import runs as run_service
from tests.helpers import make_settings
from tests.models.factories import make_connection, make_show
from tests.providers.llm.helpers import completion
from tests.providers.tts.helpers import pcm_bytes

WORDS = " ".join(["word"] * 45)
LLM_HEADER = ("X-Llm-Gateway", "llm-secret-header-123456")
TTS_HEADER = ("X-Tts-Gateway", "tts-secret-header-654321")
SCRIPT = {
    "title": "Local episode",
    "description": "Made on my own servers.",
    "segments": [
        {"speaker": "Alex", "text": f"Welcome. {WORDS}", "kind": "intro", "item_ids": []},
        {"speaker": "Sam", "text": f"Story. {WORDS}", "kind": "story", "item_ids": [1]},
        {"speaker": "Alex", "text": f"Again. {WORDS}", "kind": "story", "item_ids": [2]},
    ],
}


@respx.mock
async def test_an_llm_only_and_a_tts_only_connection_make_one_episode(
    db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    llm = await make_connection(
        db_session, admin_user, "My Ollama", base_url="http://llm.local/v1",
        headers=dict([LLM_HEADER]),
    )  # fmt: skip
    voices = await make_connection(
        db_session, admin_user, "My Kokoro", base_url="http://tts.local/v1",
        headers=dict([TTS_HEADER]), llm=False, tts=True,
    )  # fmt: skip
    show = await make_show(db_session, admin_user)
    show.target_minutes = 1
    show.llm_provider, show.llm_model = f"conn:{llm.id}", "llama3"
    items = [
        Item(
            user_id=admin_user.id,
            show_id=show.id,
            canonical_url=f"https://e.com/{n}",
            content_hash=str(n) * 64,
            title=f"Story {n}",
            summary=f"Details {n}.",
        )  # fmt: skip
        for n in (1, 2)
    ]
    db_session.add_all(items)
    for position, (name, voice) in enumerate((("Alex", "af_bella"), ("Sam", "am_michael"))):
        db_session.add(
            Speaker(
                user_id=admin_user.id,
                show_id=show.id,
                position=position,
                name=name,
                tts_provider=f"conn:{voices.id}",
                voice_id=voice,
            )  # fmt: skip
        )
    await db_session.flush()
    run = await run_service.create_run(db_session, admin_user.id, show.id)
    run.selection = {
        "stories": [
            {"item_id": str(item.id), "score": 9, "reason": "r", "supporting_item_ids": []}
            for item in items
        ]
    }
    await db_session.flush()
    cfg = make_settings(media_root=str(tmp_path), tts_retry_backoff_s=0.0)

    chat = respx.post("http://llm.local/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=completion(json.dumps(SCRIPT), model="llama3"))
    )
    speech = respx.post("http://tts.local/v1/audio/speech").respond(200, content=pcm_bytes(2400))

    stages = [Stage("script", script_stage.run, 30, 55), Stage("tts", tts_stage.run, 55, 85)]
    assert await run_stage(db_session, cfg, run.id, "script", stages=stages) is StageResult.DONE
    assert await run_stage(db_session, cfg, run.id, "tts", stages=stages) is StageResult.DONE

    # Each service got its own connection's header, and only that one.
    assert chat.calls.last.request.headers[LLM_HEADER[0]] == LLM_HEADER[1]
    assert TTS_HEADER[0].lower() not in chat.calls.last.request.headers
    assert speech.call_count == 3
    assert all(c.request.headers[TTS_HEADER[0]] == TTS_HEADER[1] for c in speech.calls)
    assert LLM_HEADER[0].lower() not in speech.calls.last.request.headers

    episode = (await db_session.scalars(select(Episode).where(Episode.run_id == run.id))).one()
    assert episode.title == "Local episode"
    manifest = json.loads((work_dir(tmp_path, run.id) / "manifest.json").read_text())
    assert {c["provider"] for c in manifest["chunks"]} == {f"conn:{voices.id}"}

    # Usage is recorded under the connection's name; with no price known the cost is unknown.
    events = (await db_session.scalars(select(UsageEvent).where(UsageEvent.run_id == run.id))).all()
    assert {(e.kind, e.provider) for e in events} == {
        (UsageKind.LLM, "conn:My Ollama"),
        (UsageKind.TTS, "conn:My Kokoro"),
    }
    assert all(e.cost_usd == 0 and e.cost_source.value == "unknown" for e in events)
