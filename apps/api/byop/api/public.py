"""What podcast apps fetch without a session: the RSS feed and the episode audio.

These live outside `/api` so the addresses stay short and stable (`/feeds/<slug>.xml`,
`/media/episodes/<id>.mp3`); `tests/api/test_guard.py` lists them as the public routes.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from sqlalchemy import select

from byop.api.audio_response import audio_response
from byop.api.deps import SessionDep, SettingsDep, StorageDep
from byop.models import Episode, Show
from byop.models.enums import EpisodeStatus
from byop.services.podcast_feed import build_feed, etag_of

router = APIRouter(tags=["public"])

FEED_CACHE = "public, max-age=300"
# A published episode's audio never changes.
MEDIA_CACHE = "public, max-age=86400"


@router.get("/feeds/{slug}.xml")
async def feed(
    slug: str,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    """The show's podcast feed (published episodes only)."""
    show = await session.scalar(select(Show).where(Show.slug == slug))
    if show is None or not show.feed_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such feed")
    episodes = list(
        await session.scalars(
            select(Episode).where(
                Episode.show_id == show.id, Episode.status == EpisodeStatus.PUBLISHED
            )
        )
    )
    body = build_feed(show, episodes, settings.public_base_url)
    etag = etag_of(body)
    headers = {"ETag": etag, "Cache-Control": FEED_CACHE}
    if request.headers.get("If-None-Match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(body, media_type="application/rss+xml; charset=utf-8", headers=headers)


@router.head("/media/episodes/{episode_id}.mp3", include_in_schema=False)
@router.get("/media/episodes/{episode_id}.mp3")
async def episode_media(
    episode_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    storage: StorageDep,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    """The audio of a published episode, with `Range` support."""
    episode = await session.scalar(
        select(Episode).where(Episode.id == episode_id, Episode.status == EpisodeStatus.PUBLISHED)
    )
    if episode is None or episode.audio_key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such episode")
    return await audio_response(
        storage,
        episode.audio_key,
        range_header,
        cache_control=MEDIA_CACHE,
        head=request.method == "HEAD",
    )
