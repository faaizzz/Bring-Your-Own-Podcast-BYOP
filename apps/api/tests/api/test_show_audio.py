import uuid
from pathlib import Path

import anyio
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import get_settings
from byop.services.show_audio import MAX_UPLOAD_BYTES
from tests.audio.helpers import silence, tone
from tests.helpers import make_settings
from tests.models.factories import make_show, make_user


@pytest.fixture(autouse=True)
def media(app: FastAPI, tmp_path: Path) -> Path:
    app.dependency_overrides[get_settings] = lambda: make_settings(
        media_root=str(tmp_path / "media")
    )
    return tmp_path / "media"


async def new_show(authed: AsyncClient) -> str:
    response = await authed.post("/api/shows", json={"title": "Daily AI", "topic": "AI"})
    return str(response.json()["id"])


async def upload(
    client: AsyncClient, show_id: str, kind: str, path: Path, name: str | None = None
) -> Response:
    data = await anyio.Path(path).read_bytes()
    return await client.post(
        f"/api/shows/{show_id}/audio/{kind}",
        files={"file": (name or path.name, data, "application/octet-stream")},
    )


async def test_a_clip_is_uploaded_stored_and_linked_from_the_show(
    authed: AsyncClient, tmp_path: Path, media: Path
) -> None:
    show_id = await new_show(authed)
    assert (await authed.get(f"/api/shows/{show_id}")).json()["intro_url"] is None

    response = await upload(authed, show_id, "intro", tone(tmp_path / "jingle.wav", 2.0))

    assert response.status_code == 200
    body = response.json()
    assert body["intro_url"].startswith(f"/api/shows/{show_id}/audio/intro?v=")
    assert body["outro_url"] is None and body["music_url"] is None
    assert (media / "shows" / show_id / "audio" / "intro.wav").is_file()


async def test_the_owner_can_play_the_clip_back(authed: AsyncClient, tmp_path: Path) -> None:
    show_id = await new_show(authed)
    source = tone(tmp_path / "jingle.wav", 1.0)
    url = (await upload(authed, show_id, "intro", source)).json()["intro_url"]

    response = await authed.get(url)

    assert response.status_code == 200
    assert (
        response.headers["content-type"] == "audio/x-wav"
        or "wav" in response.headers["content-type"]
    )
    assert response.content == source.read_bytes()
    assert int(response.headers["content-length"]) == len(response.content)


@pytest.mark.parametrize("kind", ["intro", "outro", "music"])
async def test_all_three_kinds_work(authed: AsyncClient, tmp_path: Path, kind: str) -> None:
    show_id = await new_show(authed)

    response = await upload(authed, show_id, kind, tone(tmp_path / "a.mp3", 1.0))

    assert response.status_code == 200 and response.json()[f"{kind}_url"] is not None


async def test_replacing_with_another_format_removes_the_old_file(
    authed: AsyncClient, tmp_path: Path, media: Path
) -> None:
    show_id = await new_show(authed)
    await upload(authed, show_id, "music", tone(tmp_path / "bed.wav", 1.0))

    await upload(authed, show_id, "music", tone(tmp_path / "bed.mp3", 1.0))

    files = sorted(p.name for p in (media / "shows" / show_id / "audio").iterdir())
    assert files == ["music.mp3"]


async def test_a_clip_can_be_removed(authed: AsyncClient, tmp_path: Path, media: Path) -> None:
    show_id = await new_show(authed)
    await upload(authed, show_id, "outro", tone(tmp_path / "o.wav", 1.0))

    response = await authed.delete(f"/api/shows/{show_id}/audio/outro")

    assert response.status_code == 200 and response.json()["outro_url"] is None
    assert not (media / "shows" / show_id / "audio" / "outro.wav").exists()
    assert (await authed.get(f"/api/shows/{show_id}/audio/outro")).status_code == 404
    assert (
        await authed.delete(f"/api/shows/{show_id}/audio/outro")
    ).status_code == 200  # idempotent


async def test_files_that_are_not_audio_are_rejected_with_a_reason(
    authed: AsyncClient, tmp_path: Path
) -> None:
    show_id = await new_show(authed)
    fake = tmp_path / "fake.mp3"
    fake.write_bytes(b"definitely not audio")
    text = tmp_path / "notes.txt"
    text.write_text("hello")

    corrupt = await upload(authed, show_id, "intro", fake)
    wrong_type = await upload(authed, show_id, "intro", text)

    assert corrupt.status_code == 422 and "not readable audio" in corrupt.json()["detail"]
    assert wrong_type.status_code == 422 and "Use an audio file" in wrong_type.json()["detail"]
    assert (await authed.get(f"/api/shows/{show_id}")).json()["intro_url"] is None


async def test_jingles_are_limited_in_length_but_a_bed_may_be_long(
    authed: AsyncClient, tmp_path: Path
) -> None:
    show_id = await new_show(authed)
    long_clip = silence(tmp_path / "long.wav", 130.0, rate=8000)

    too_long = await upload(authed, show_id, "intro", long_clip)
    bed = await upload(authed, show_id, "music", long_clip)

    assert too_long.status_code == 422 and "most allowed is 2 minutes" in too_long.json()["detail"]
    assert bed.status_code == 200


async def test_oversized_uploads_are_refused(authed: AsyncClient) -> None:
    show_id = await new_show(authed)

    response = await authed.post(
        f"/api/shows/{show_id}/audio/music",
        files={"file": ("big.mp3", b"0" * (MAX_UPLOAD_BYTES + 10), "audio/mpeg")},
    )

    assert response.status_code == 413 and "25 MB" in response.json()["detail"]


async def test_unknown_kinds_and_shows_are_rejected(
    authed: AsyncClient, tmp_path: Path, db_session: AsyncSession
) -> None:
    show_id = await new_show(authed)
    clip = tone(tmp_path / "a.wav", 1.0)
    other = await make_user(db_session, "other@example.com")
    theirs = await make_show(db_session, other, slug="theirs")

    assert (await upload(authed, show_id, "podcast", clip)).status_code == 422
    assert (await upload(authed, str(uuid.uuid4()), "intro", clip)).status_code == 404
    assert (await upload(authed, str(theirs.id), "intro", clip)).status_code == 404
    assert (await authed.delete(f"/api/shows/{theirs.id}/audio/intro")).status_code == 404
    assert (await authed.get(f"/api/shows/{theirs.id}/audio/intro")).status_code == 404


async def test_deleting_the_show_removes_its_clips(
    authed: AsyncClient, tmp_path: Path, media: Path
) -> None:
    show_id = await new_show(authed)
    await upload(authed, show_id, "intro", tone(tmp_path / "a.wav", 1.0))

    await authed.delete(f"/api/shows/{show_id}")

    assert not (media / "shows" / show_id).exists()


async def test_requires_a_session(client: AsyncClient) -> None:
    some = uuid.uuid4()

    assert (await client.post(f"/api/shows/{some}/audio/intro")).status_code == 401
    assert (await client.delete(f"/api/shows/{some}/audio/intro")).status_code == 401
    assert (await client.get(f"/api/shows/{some}/audio/intro")).status_code == 401
