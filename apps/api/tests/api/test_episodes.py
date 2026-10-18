import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from kombu.exceptions import OperationalError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from byop.api import episodes as episodes_api
from byop.config import get_settings
from byop.models import Episode, Item, Run, Source, Speaker, User
from byop.models.enums import (
    EpisodeStatus,
    RunStatus,
    RunTrigger,
    SourceKind,
)
from byop.storage import LocalStorage
from byop.tasks.pipeline import RESYNTH_STAGES
from tests.helpers import make_settings
from tests.models.factories import make_show, make_user

AUDIO = bytes(range(256)) * 40  # 10240 bytes with a recognisable pattern


class Spy:
    def __init__(self) -> None:
        self.enqueued: list[tuple[uuid.UUID, tuple[str, ...]]] = []


@pytest.fixture
def broker(monkeypatch: pytest.MonkeyPatch) -> Spy:
    spy = Spy()

    def enqueue(run_id: uuid.UUID, names: object = None) -> str:
        spy.enqueued.append((run_id, tuple(names)))  # type: ignore[arg-type]
        return "task-1"

    monkeypatch.setattr(episodes_api, "enqueue_run", enqueue)
    return spy


@pytest.fixture(autouse=True)
def media(app: FastAPI, tmp_path: Path) -> Path:
    app.dependency_overrides[get_settings] = lambda: make_settings(media_root=str(tmp_path))
    return tmp_path


SEGMENTS = [
    {"speaker": "Alex", "text": "Welcome to the show.", "kind": "intro", "item_ids": []},
    {"speaker": "Sam", "text": "Sonar maps the ocean.", "kind": "story", "item_ids": ["s1"]},
    {"speaker": "Alex", "text": "That is all.", "kind": "outro", "item_ids": []},
]


async def draft(
    session: AsyncSession,
    user: User,
    tmp_path: Path,
    *,
    audio: bool = True,
    current: bool = True,
    run_status: RunStatus = RunStatus.AWAITING_REVIEW,
    status: EpisodeStatus = EpisodeStatus.DRAFT,
) -> Episode:
    """A show with two speakers and a drafted episode whose run is waiting for review."""
    show = await make_show(session, user, slug=f"show-{uuid.uuid4().hex[:6]}")
    session.add_all(
        [
            Speaker(
                user_id=user.id, show_id=show.id, position=i, name=name,
                tts_provider="kokoro", voice_id="af_bella",
            )
            for i, name in enumerate(["Alex", "Sam"])
        ]
    )  # fmt: skip
    run = Run(user_id=user.id, show_id=show.id, trigger=RunTrigger.MANUAL, status=run_status)
    session.add(run)
    await session.flush()
    episode = Episode(
        user_id=user.id,
        show_id=show.id,
        run_id=run.id,
        title="Oceans",
        description="Sonar maps.",
        status=status,
        script={
            "version": 1,
            "revision": 1,
            "audio_revision": (1 if current else None) if audio else None,
            "segments": [dict(s) for s in SEGMENTS],
        },
    )
    session.add(episode)
    await session.flush()
    if audio:
        key = f"shows/{show.id}/episodes/{episode.id}/audio.mp3"
        await LocalStorage(tmp_path).put(key, AUDIO, content_type="audio/mpeg")
        episode.audio_key = key
        episode.duration_s = 90
        episode.size_bytes = len(AUDIO)
    await session.flush()
    return episode


def edited(text: str = "A new opening.") -> list[dict[str, Any]]:
    return [{**SEGMENTS[0], "text": text}, *SEGMENTS[1:]]


# --- reading -----------------------------------------------------------------------------------


async def test_an_episode_is_returned_with_its_script_and_review_state(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    episode = await draft(db_session, admin_user, tmp_path)

    response = await authed.get(f"/api/episodes/{episode.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Oceans" and body["status"] == "draft"
    assert [s["speaker"] for s in body["segments"]] == ["Alex", "Sam", "Alex"]
    assert body["segments"][1]["item_ids"] == ["s1"]
    assert body["speakers"] == ["Alex", "Sam"]
    assert body["revision"] == 1 and body["audio_revision"] == 1 and body["audio_current"] is True
    assert body["audio_url"].startswith(f"/api/episodes/{episode.id}/audio")
    assert body["duration_s"] == 90 and body["size_bytes"] == len(AUDIO)
    assert body["run"]["status"] == "awaiting_review" and body["run"]["trigger"] == "manual"


async def test_an_episode_without_audio_has_no_audio_url(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    episode = await draft(db_session, admin_user, tmp_path, audio=False)

    body = (await authed.get(f"/api/episodes/{episode.id}")).json()

    assert body["audio_url"] is None and body["audio_current"] is False


async def test_an_episode_from_before_revisions_counts_as_revision_one(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    episode = await draft(db_session, admin_user, tmp_path)
    episode.script = {"segments": SEGMENTS}
    await db_session.flush()

    body = (await authed.get(f"/api/episodes/{episode.id}")).json()

    assert body["revision"] == 1 and body["audio_revision"] is None
    assert body["audio_current"] is False  # nobody can tell which script it was voiced from


async def test_someone_elses_episode_is_not_found(
    authed: AsyncClient, db_session: AsyncSession, tmp_path: Path
) -> None:
    other = await make_user(db_session, "other@example.com")
    episode = await draft(db_session, other, tmp_path)

    for method, path in [
        ("GET", ""),
        ("PATCH", ""),
        ("POST", "/approve"),
        ("POST", "/reject"),
        ("POST", "/resynthesize"),
        ("GET", "/audio"),
    ]:
        response = await authed.request(method, f"/api/episodes/{episode.id}{path}", json={})
        assert response.status_code == 404, (method, path)
    assert (await authed.get(f"/api/episodes/{uuid.uuid4()}")).status_code == 404


async def test_a_shows_episodes_are_listed_newest_first_and_can_be_filtered(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    first = await draft(db_session, admin_user, tmp_path)
    second = Episode(
        user_id=admin_user.id, show_id=first.show_id, title="Later", status=EpisodeStatus.PUBLISHED,
        published_at=datetime.now(UTC), created_at=datetime.now(UTC) + timedelta(minutes=1),
    )  # fmt: skip
    db_session.add(second)
    await db_session.flush()

    listed = (await authed.get(f"/api/shows/{first.show_id}/episodes")).json()
    drafts = (await authed.get(f"/api/shows/{first.show_id}/episodes?status=draft")).json()

    assert [e["title"] for e in listed] == ["Later", "Oceans"]
    assert [e["title"] for e in drafts] == ["Oceans"]
    assert drafts[0]["run"]["status"] == "awaiting_review"
    assert (await authed.get(f"/api/shows/{uuid.uuid4()}/episodes")).status_code == 404


# --- editing -----------------------------------------------------------------------------------


async def test_editing_the_script_bumps_the_revision_and_outdates_the_audio(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    episode = await draft(db_session, admin_user, tmp_path)

    response = await authed.patch(f"/api/episodes/{episode.id}", json={"segments": edited()})

    assert response.status_code == 200
    body = response.json()
    assert body["segments"][0]["text"] == "A new opening."
    assert body["revision"] == 2 and body["audio_revision"] == 1
    assert body["audio_current"] is False


async def test_saving_an_unchanged_script_keeps_the_audio_current(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    episode = await draft(db_session, admin_user, tmp_path)

    body = (await authed.patch(f"/api/episodes/{episode.id}", json={"segments": SEGMENTS})).json()

    assert body["revision"] == 1 and body["audio_current"] is True


async def test_the_title_and_description_can_change_without_new_audio(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    episode = await draft(db_session, admin_user, tmp_path)

    response = await authed.patch(
        f"/api/episodes/{episode.id}", json={"title": "  Better title ", "description": "New."}
    )

    body = response.json()
    assert body["title"] == "Better title" and body["description"] == "New."
    assert body["segments"][0]["text"] == SEGMENTS[0]["text"]
    assert body["revision"] == 1 and body["audio_current"] is True


async def test_speakers_are_matched_ignoring_case(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    episode = await draft(db_session, admin_user, tmp_path)
    segments = [{**SEGMENTS[0], "speaker": "alex"}, *SEGMENTS[1:]]

    body = (await authed.patch(f"/api/episodes/{episode.id}", json={"segments": segments})).json()

    assert body["segments"][0]["speaker"] == "Alex"
    assert body["revision"] == 1  # same script after canonical naming


@pytest.mark.parametrize(
    ("segments", "loc", "message"),
    [
        ([{**SEGMENTS[0], "speaker": "Nobody"}], ["body", "segments", 0, "speaker"], "speaker"),
        ([SEGMENTS[0], {**SEGMENTS[1], "text": "   "}], ["body", "segments", 1, "text"], "empty"),
    ],
)
async def test_an_invalid_script_is_rejected_per_segment(
    authed: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    tmp_path: Path,
    segments: list[dict[str, object]],
    loc: list[object],
    message: str,
) -> None:
    episode = await draft(db_session, admin_user, tmp_path)

    response = await authed.patch(f"/api/episodes/{episode.id}", json={"segments": segments})

    assert response.status_code == 422
    error = response.json()["detail"][0]
    assert error["loc"] == loc and message in error["msg"]
    await db_session.refresh(episode)
    assert episode.script is not None and episode.script["revision"] == 1  # nothing was saved


async def test_a_script_needs_at_least_one_segment_and_a_title_cannot_be_blank(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    episode = await draft(db_session, admin_user, tmp_path)

    assert (
        await authed.patch(f"/api/episodes/{episode.id}", json={"segments": []})
    ).status_code == 422
    assert (
        await authed.patch(f"/api/episodes/{episode.id}", json={"title": "  "})
    ).status_code == 422


async def test_a_published_episode_cannot_be_edited(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    episode = await draft(
        db_session,
        admin_user,
        tmp_path,
        status=EpisodeStatus.PUBLISHED,
        run_status=RunStatus.SUCCEEDED,
    )

    response = await authed.patch(f"/api/episodes/{episode.id}", json={"title": "Changed"})

    assert response.status_code == 409 and "published" in response.json()["detail"]


async def test_a_draft_cannot_be_edited_while_a_run_is_working_on_it(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    episode = await draft(db_session, admin_user, tmp_path, run_status=RunStatus.RUNNING)

    response = await authed.patch(f"/api/episodes/{episode.id}", json={"segments": edited()})

    assert response.status_code == 409 and "run" in response.json()["detail"]


# --- approving ---------------------------------------------------------------------------------


async def test_approving_publishes_the_draft_and_closes_its_run(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    episode = await draft(db_session, admin_user, tmp_path)

    response = await authed.post(f"/api/episodes/{episode.id}/approve")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "published" and body["published_at"] is not None
    assert body["run"]["status"] == "succeeded"
    assert await LocalStorage(tmp_path).exists(episode.audio_key or "")  # the audio stays


async def test_approval_is_blocked_while_the_script_differs_from_the_audio(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    episode = await draft(db_session, admin_user, tmp_path)
    await authed.patch(f"/api/episodes/{episode.id}", json={"segments": edited()})

    response = await authed.post(f"/api/episodes/{episode.id}/approve")

    assert response.status_code == 409 and "re-synthesize" in response.json()["detail"]
    await db_session.refresh(episode)
    assert episode.status is EpisodeStatus.DRAFT and episode.published_at is None


async def test_a_draft_without_audio_cannot_be_approved(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    episode = await draft(db_session, admin_user, tmp_path, audio=False)

    response = await authed.post(f"/api/episodes/{episode.id}/approve")

    assert response.status_code == 409 and "no audio" in response.json()["detail"]


async def test_an_episode_cannot_be_approved_twice_or_after_rejection(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    episode = await draft(db_session, admin_user, tmp_path)
    assert (await authed.post(f"/api/episodes/{episode.id}/approve")).status_code == 200

    assert (await authed.post(f"/api/episodes/{episode.id}/approve")).status_code == 409
    assert (await authed.post(f"/api/episodes/{episode.id}/reject")).status_code == 409


# --- rejecting ---------------------------------------------------------------------------------


async def test_rejecting_releases_the_stories_and_deletes_the_audio(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    episode = await draft(db_session, admin_user, tmp_path)
    source = Source(
        user_id=admin_user.id, show_id=episode.show_id, kind=SourceKind.RSS, value="https://e.com/r"
    )
    db_session.add(source)
    await db_session.flush()
    db_session.add_all(
        [
            Item(
                user_id=admin_user.id, show_id=episode.show_id, source_id=source.id,
                canonical_url=f"https://e.com/{n}", content_hash=f"h{n}", title=f"Story {n}",
                used_in_episode_id=episode.id,
            )
            for n in range(2)
        ]
    )  # fmt: skip
    await db_session.flush()
    key = episode.audio_key or ""

    response = await authed.post(f"/api/episodes/{episode.id}/reject")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected" and body["audio_url"] is None
    assert body["run"]["status"] == "succeeded"
    assert not await LocalStorage(tmp_path).exists(key)
    items = list(await db_session.scalars(select(Item).where(Item.show_id == episode.show_id)))
    assert {i.used_in_episode_id for i in items} == {None}
    assert (await authed.post(f"/api/episodes/{episode.id}/approve")).status_code == 409


async def test_rejecting_leaves_other_episodes_stories_alone(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    episode = await draft(db_session, admin_user, tmp_path)
    kept = Episode(user_id=admin_user.id, show_id=episode.show_id, title="Earlier")
    source = Source(
        user_id=admin_user.id, show_id=episode.show_id, kind=SourceKind.RSS, value="https://e.com/r"
    )
    db_session.add_all([kept, source])
    await db_session.flush()
    item = Item(
        user_id=admin_user.id, show_id=episode.show_id, source_id=source.id,
        canonical_url="https://e.com/old", content_hash="old", title="Old story",
        used_in_episode_id=kept.id,
    )  # fmt: skip
    db_session.add(item)
    await db_session.flush()

    await authed.post(f"/api/episodes/{episode.id}/reject")

    await db_session.refresh(item)
    assert item.used_in_episode_id == kept.id


# --- re-synthesizing ---------------------------------------------------------------------------


async def test_resynthesizing_queues_only_voice_and_mix_and_moves_the_episode_to_the_new_run(
    authed: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    tmp_path: Path,
    broker: Spy,
) -> None:
    episode = await draft(db_session, admin_user, tmp_path)
    old_run_id = episode.run_id
    await authed.patch(f"/api/episodes/{episode.id}", json={"segments": edited()})

    response = await authed.post(f"/api/episodes/{episode.id}/resynthesize")

    assert response.status_code == 202
    body = response.json()
    assert body["run"]["trigger"] == "resynth" and body["run"]["status"] == "queued"
    assert body["run"]["id"] != str(old_run_id)
    assert broker.enqueued == [(uuid.UUID(body["run"]["id"]), RESYNTH_STAGES)]
    assert RESYNTH_STAGES == ("tts", "mix", "finalize")
    old = await db_session.get(Run, old_run_id, populate_existing=True)
    assert old is not None and old.status is RunStatus.SUCCEEDED
    # Until the new audio lands the old one is out of date, so approval stays blocked.
    assert (await authed.post(f"/api/episodes/{episode.id}/approve")).status_code == 409


async def test_resynthesizing_is_refused_while_a_run_is_active(
    authed: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    tmp_path: Path,
    broker: Spy,
) -> None:
    episode = await draft(db_session, admin_user, tmp_path)
    assert (await authed.post(f"/api/episodes/{episode.id}/resynthesize")).status_code == 202

    again = await authed.post(f"/api/episodes/{episode.id}/resynthesize")

    assert again.status_code == 409
    assert len(broker.enqueued) == 1


async def test_a_published_episode_cannot_be_voiced_again(
    authed: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    tmp_path: Path,
    broker: Spy,
) -> None:
    episode = await draft(
        db_session,
        admin_user,
        tmp_path,
        status=EpisodeStatus.PUBLISHED,
        run_status=RunStatus.SUCCEEDED,
    )

    response = await authed.post(f"/api/episodes/{episode.id}/resynthesize")

    assert response.status_code == 409 and broker.enqueued == []


async def test_a_job_queue_outage_fails_the_new_run_instead_of_leaving_it_queued(
    authed: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    episode = await draft(db_session, admin_user, tmp_path)

    def down(run_id: uuid.UUID, names: object = None) -> str:
        raise OperationalError("broker down")

    monkeypatch.setattr(episodes_api, "enqueue_run", down)

    response = await authed.post(f"/api/episodes/{episode.id}/resynthesize")

    assert response.status_code == 503
    body = (await authed.get(f"/api/episodes/{episode.id}")).json()
    assert body["run"]["status"] == "failed"
    assert "queue" in body["run"]["error"]


# --- audio -------------------------------------------------------------------------------------


async def test_the_audio_is_streamed_and_advertises_range_support(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    episode = await draft(db_session, admin_user, tmp_path)

    response = await authed.get(f"/api/episodes/{episode.id}/audio")

    assert response.status_code == 200
    assert response.content == AUDIO
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == str(len(AUDIO))


@pytest.mark.parametrize(
    ("header", "start", "end"),
    [("bytes=0-99", 0, 99), ("bytes=10000-", 10000, 10239), ("bytes=-16", 10224, 10239)],
)
async def test_a_range_request_gets_just_those_bytes(
    authed: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    tmp_path: Path,
    header: str,
    start: int,
    end: int,
) -> None:
    episode = await draft(db_session, admin_user, tmp_path)

    response = await authed.get(f"/api/episodes/{episode.id}/audio", headers={"Range": header})

    assert response.status_code == 206
    assert response.content == AUDIO[start : end + 1]
    assert response.headers["content-range"] == f"bytes {start}-{end}/{len(AUDIO)}"
    assert response.headers["content-length"] == str(end - start + 1)


async def test_a_range_past_the_end_is_not_satisfiable(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    episode = await draft(db_session, admin_user, tmp_path)

    response = await authed.get(
        f"/api/episodes/{episode.id}/audio", headers={"Range": "bytes=99999-"}
    )

    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(AUDIO)}"


async def test_an_episode_without_audio_has_nothing_to_stream(
    authed: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    episode = await draft(db_session, admin_user, tmp_path, audio=False)

    assert (await authed.get(f"/api/episodes/{episode.id}/audio")).status_code == 404


async def test_the_audio_needs_a_session(
    client: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    episode = await draft(db_session, admin_user, tmp_path)

    assert (await client.get(f"/api/episodes/{episode.id}/audio")).status_code == 401
