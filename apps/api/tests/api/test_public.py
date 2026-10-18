import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from byop.config import get_settings
from byop.models import Episode, Show, User
from byop.models.enums import EpisodeStatus
from byop.storage import LocalStorage
from tests.helpers import make_settings
from tests.models.factories import make_show

AUDIO = bytes(range(256)) * 40  # 10240 bytes with a recognisable pattern
BASE = "https://pods.example.com"


@pytest.fixture(autouse=True)
def media(app: FastAPI, tmp_path: Path) -> Path:
    app.dependency_overrides[get_settings] = lambda: make_settings(
        media_root=str(tmp_path), public_base_url=BASE
    )
    return tmp_path


async def episode_with_audio(
    session: AsyncSession,
    user: User,
    show: Show,
    tmp_path: Path,
    *,
    status: EpisodeStatus = EpisodeStatus.PUBLISHED,
    title: str = "Oceans",
) -> Episode:
    episode = Episode(
        user_id=user.id,
        show_id=show.id,
        title=title,
        status=status,
        published_at=datetime(2026, 5, 1, tzinfo=UTC)
        if status is EpisodeStatus.PUBLISHED
        else None,
        size_bytes=len(AUDIO),
        duration_s=300,
    )
    session.add(episode)
    await session.flush()
    key = f"shows/{show.id}/episodes/{episode.id}/audio.mp3"
    await LocalStorage(tmp_path).put(key, AUDIO, content_type="audio/mpeg")
    episode.audio_key = key
    await session.flush()
    return episode


# --- the feed -----------------------------------------------------------------------------------


async def test_the_feed_is_public_valid_xml_with_published_episodes_only(
    client: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    show = await make_show(db_session, admin_user)
    published = await episode_with_audio(db_session, admin_user, show, tmp_path)
    await episode_with_audio(
        db_session, admin_user, show, tmp_path, status=EpisodeStatus.DRAFT, title="Draft"
    )

    response = await client.get("/feeds/daily-ai.xml")  # no session

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/rss+xml")
    assert "max-age" in response.headers["cache-control"]
    root = ET.fromstring(response.content)
    items = root.findall("channel/item")
    assert [i.findtext("title") for i in items] == ["Oceans"]
    enclosure = items[0].find("enclosure")
    assert enclosure is not None
    assert enclosure.attrib["url"] == f"{BASE}/media/episodes/{published.id}.mp3"
    assert enclosure.attrib["length"] == str(len(AUDIO))
    assert enclosure.attrib["type"] == "audio/mpeg"


async def test_an_unknown_or_disabled_feed_is_404(
    client: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    show = await make_show(db_session, admin_user)

    assert (await client.get("/feeds/nope.xml")).status_code == 404

    show.feed_enabled = False
    await db_session.flush()
    assert (await client.get("/feeds/daily-ai.xml")).status_code == 404


async def test_the_feed_supports_conditional_requests(
    client: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    show = await make_show(db_session, admin_user)
    await episode_with_audio(db_session, admin_user, show, tmp_path)

    first = await client.get("/feeds/daily-ai.xml")
    etag = first.headers["etag"]
    same = await client.get("/feeds/daily-ai.xml", headers={"If-None-Match": etag})
    other = await client.get("/feeds/daily-ai.xml", headers={"If-None-Match": '"stale"'})

    assert same.status_code == 304 and same.content == b""
    assert other.status_code == 200 and other.headers["etag"] == etag


async def test_a_new_episode_changes_the_feed_and_its_etag(
    client: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    show = await make_show(db_session, admin_user)
    await episode_with_audio(db_session, admin_user, show, tmp_path)
    before = (await client.get("/feeds/daily-ai.xml")).headers["etag"]

    await episode_with_audio(db_session, admin_user, show, tmp_path, title="Second")

    response = await client.get("/feeds/daily-ai.xml")
    assert response.headers["etag"] != before
    assert len(ET.fromstring(response.content).findall("channel/item")) == 2


async def test_the_show_settings_end_up_in_the_feed(
    authed: AsyncClient, client: AsyncClient
) -> None:
    created = await authed.post(
        "/api/shows",
        json={
            "title": "Tech Weekly",
            "topic": "Tech",
            "description": "The week in tech.",
            "feed_author": "Ada Lovelace",
            "feed_email": "ada@example.com",
            "feed_category": "Technology",
            "feed_explicit": True,
        },
    )
    assert created.status_code == 201
    assert created.json()["feed_url"] == f"{BASE}/feeds/tech-weekly.xml"

    root = ET.fromstring((await client.get("/feeds/tech-weekly.xml")).content)

    ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
    assert root.findtext("channel/description") == "The week in tech."
    assert root.findtext("channel/itunes:author", namespaces=ns) == "Ada Lovelace"
    assert root.findtext("channel/itunes:explicit", namespaces=ns) == "true"


async def test_the_feed_can_be_switched_off_and_on(
    authed: AsyncClient, client: AsyncClient
) -> None:
    show = (await authed.post("/api/shows", json={"title": "Daily AI", "topic": "AI"})).json()
    assert show["feed_enabled"] is True
    assert (await client.get("/feeds/daily-ai.xml")).status_code == 200

    off = await authed.patch(f"/api/shows/{show['id']}", json={"feed_enabled": False})
    assert off.json()["feed_enabled"] is False
    assert (await client.get("/feeds/daily-ai.xml")).status_code == 404

    await authed.patch(f"/api/shows/{show['id']}", json={"feed_enabled": True})
    assert (await client.get("/feeds/daily-ai.xml")).status_code == 200


# --- the audio ----------------------------------------------------------------------------------


async def media_url(
    session: AsyncSession, user: User, tmp_path: Path, **values: object
) -> tuple[str, Episode]:
    show = await make_show(session, user)
    episode = await episode_with_audio(session, user, show, tmp_path, **values)  # type: ignore[arg-type]
    return f"/media/episodes/{episode.id}.mp3", episode


async def test_published_audio_is_public_and_seekable(
    client: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    url, _ = await media_url(db_session, admin_user, tmp_path)

    whole = await client.get(url)
    assert whole.status_code == 200 and whole.content == AUDIO
    assert whole.headers["content-type"] == "audio/mpeg"
    assert whole.headers["accept-ranges"] == "bytes"
    assert whole.headers["content-length"] == str(len(AUDIO))
    assert "public" in whole.headers["cache-control"]

    part = await client.get(url, headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and part.content == AUDIO[100:200]
    assert part.headers["content-range"] == f"bytes 100-199/{len(AUDIO)}"
    assert part.headers["content-length"] == "100"

    tail = await client.get(url, headers={"Range": "bytes=10000-"})
    assert tail.status_code == 206 and tail.content == AUDIO[10000:]

    suffix = await client.get(url, headers={"Range": "bytes=-16"})
    assert suffix.status_code == 206 and suffix.content == AUDIO[-16:]


async def test_a_range_past_the_end_is_416(
    client: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    url, _ = await media_url(db_session, admin_user, tmp_path)

    response = await client.get(url, headers={"Range": "bytes=99999-"})

    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(AUDIO)}"


async def test_head_returns_the_headers_without_a_body(
    client: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    url, _ = await media_url(db_session, admin_user, tmp_path)

    response = await client.head(url)

    assert response.status_code == 200 and response.content == b""
    assert response.headers["content-length"] == str(len(AUDIO))
    assert response.headers["content-type"] == "audio/mpeg"


async def test_drafts_and_unknown_episodes_have_no_public_audio(
    client: AsyncClient, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    url, _ = await media_url(db_session, admin_user, tmp_path, status=EpisodeStatus.DRAFT)

    assert (await client.get(url)).status_code == 404
    assert (await client.get(f"/media/episodes/{uuid.uuid4()}.mp3")).status_code == 404
    assert (await client.get("/media/episodes/not-a-uuid.mp3")).status_code == 422


# --- rate limits and cross-origin access ---------------------------------------------------


async def test_the_feed_is_rate_limited_per_client(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    app.dependency_overrides[get_settings] = lambda: make_settings(
        media_root=str(tmp_path), public_base_url=BASE, public_feed_rate_per_minute=3
    )
    await make_show(db_session, admin_user)

    statuses = [(await client.get("/feeds/daily-ai.xml")).status_code for _ in range(5)]
    refused = await client.get("/feeds/daily-ai.xml")

    assert statuses == [200, 200, 200, 429, 429]
    assert refused.headers["retry-after"].isdigit() and int(refused.headers["retry-after"]) >= 1
    # Another client address has its own allowance (the last forwarded address is the real one).
    other = await client.get("/feeds/daily-ai.xml", headers={"X-Forwarded-For": "203.0.113.9"})
    assert other.status_code == 200


async def test_audio_has_its_own_limit_separate_from_the_feed(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    app.dependency_overrides[get_settings] = lambda: make_settings(
        media_root=str(tmp_path),
        public_base_url=BASE,
        public_feed_rate_per_minute=1,
        public_media_rate_per_minute=2,
    )
    url, _ = await media_url(db_session, admin_user, tmp_path)

    assert (await client.get("/feeds/daily-ai.xml")).status_code == 200
    assert (await client.get("/feeds/daily-ai.xml")).status_code == 429
    assert [(await client.get(url)).status_code for _ in range(3)] == [200, 200, 429]
    assert (await client.head(url)).status_code == 429  # HEAD counts too


async def test_a_limit_of_zero_switches_the_check_off(
    client: AsyncClient, app: FastAPI, db_session: AsyncSession, admin_user: User, tmp_path: Path
) -> None:
    app.dependency_overrides[get_settings] = lambda: make_settings(
        media_root=str(tmp_path), public_base_url=BASE, public_feed_rate_per_minute=0
    )
    await make_show(db_session, admin_user)

    assert {(await client.get("/feeds/daily-ai.xml")).status_code for _ in range(10)} == {200}


async def test_other_origins_get_no_cross_origin_permission(
    authed: AsyncClient, client: AsyncClient
) -> None:
    """There is no CORS middleware: browsers keep the API and the feed same-origin."""
    headers = {"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}

    preflight = await authed.options("/api/shows", headers=headers)
    simple = await authed.get("/api/shows", headers={"Origin": "https://evil.example"})
    feed = await client.get("/feeds/none.xml", headers={"Origin": "https://evil.example"})

    for response in (preflight, simple, feed):
        assert not any(h.lower().startswith("access-control-") for h in response.headers)
    assert preflight.status_code in (400, 405)
