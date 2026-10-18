"""Reviewing a drafted episode: edit its script, voice it again, publish it or throw it away.

A script has a `revision` that every edit bumps; the audio remembers the revision it was voiced
from. An episode can only be approved while they match, so nothing goes out that nobody heard.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from byop.models import Episode, Item, Run, Source, Speaker
from byop.models.enums import EpisodeStatus, RunStatus, RunTrigger
from byop.pipeline.orchestrator import ACTIVE, add_event
from byop.schemas.episode import EpisodeUpdate, SegmentIn
from byop.services import runs
from byop.services.script_revision import audio_is_current, revision_of
from byop.services.shows import get_show
from byop.services.validation import FieldError, FieldValidationError
from byop.storage import Storage


class EpisodeNotFound(Exception):
    pass


class EpisodeConflict(Exception):
    """The episode's state does not allow this (already published, a run is working on it, ...)."""


async def get_episode(session: AsyncSession, user_id: uuid.UUID, episode_id: uuid.UUID) -> Episode:
    episode = await session.scalar(
        select(Episode)
        .where(Episode.id == episode_id, Episode.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    if episode is None:
        raise EpisodeNotFound
    return episode


async def list_episodes(
    session: AsyncSession,
    user_id: uuid.UUID,
    show_id: uuid.UUID,
    *,
    status: EpisodeStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Episode]:
    await get_show(session, user_id, show_id)  # 404 for someone else's show
    query = select(Episode).where(Episode.show_id == show_id, Episode.user_id == user_id)
    if status is not None:
        query = query.where(Episode.status == status)
    rows = await session.scalars(
        query.order_by(Episode.created_at.desc(), Episode.id).limit(limit).offset(offset)
    )
    return list(rows)


async def runs_of(
    session: AsyncSession, user_id: uuid.UUID, episodes: list[Episode]
) -> dict[uuid.UUID, Run]:
    """The run each episode currently belongs to."""
    ids = [e.run_id for e in episodes if e.run_id is not None]
    if not ids:
        return {}
    rows = await session.scalars(
        select(Run)
        .where(Run.id.in_(ids), Run.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    return {run.id: run for run in rows}


async def sources_of(
    session: AsyncSession, user_id: uuid.UUID, episode_id: uuid.UUID
) -> list[tuple[Item, str | None]]:
    """The stories the episode was made from, each with the name of its source."""
    rows = await session.execute(
        select(Item, Source.name)
        .outerjoin(Source, Source.id == Item.source_id)
        .where(Item.used_in_episode_id == episode_id, Item.user_id == user_id)
        .order_by(Item.published_at.desc().nulls_last(), Item.id)
    )
    return [(item, name) for item, name in rows.all()]


async def speaker_names(session: AsyncSession, user_id: uuid.UUID, show_id: uuid.UUID) -> list[str]:
    rows = await session.scalars(
        select(Speaker.name)
        .where(Speaker.show_id == show_id, Speaker.user_id == user_id)
        .order_by(Speaker.position)
    )
    return list(rows)


def segments_of(episode: Episode) -> list[SegmentIn]:
    raw = (episode.script or {}).get("segments")
    segments: list[SegmentIn] = []
    for entry in raw if isinstance(raw, list) else []:
        segments.append(
            SegmentIn(
                speaker=str(entry.get("speaker", "")) or "?",
                text=str(entry.get("text", "")),
                kind=entry.get("kind", "story"),
                item_ids=[str(i) for i in entry.get("item_ids", [])],
            )
        )
    return segments


def is_audio_current(episode: Episode) -> bool:
    return audio_is_current(episode.script, episode.audio_key is not None)


async def _save(session: AsyncSession, episode: Episode) -> Episode:
    """Commit, then reload: `updated_at` is set by the database and expires on update, and async
    code cannot lazy-load it later."""
    await session.commit()
    await session.refresh(episode)
    return episode


async def _require_idle_draft(session: AsyncSession, episode: Episode, what: str) -> None:
    if episode.status is not EpisodeStatus.DRAFT:
        raise EpisodeConflict(f"The episode is {episode.status.value}; only drafts can {what}")
    active = await session.scalar(
        select(Run.id).where(Run.show_id == episode.show_id, Run.status.in_(ACTIVE)).limit(1)
    )
    if active is not None:
        raise EpisodeConflict("A run is still working on this show; wait for it to finish")


def _checked_segments(segments: list[SegmentIn], speakers: list[str]) -> list[dict[str, Any]]:
    """Normalize edited segments; speakers must be the show's (matched ignoring case)."""
    by_lower = {name.lower(): name for name in speakers}
    errors: list[FieldError] = []
    out: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        name = by_lower.get(segment.speaker.lower())
        if name is None:
            errors.append(
                FieldError(
                    ("body", "segments", index, "speaker"),
                    f"{segment.speaker!r} is not a speaker of this show",
                )
            )
        if not segment.text:
            errors.append(FieldError(("body", "segments", index, "text"), "Text cannot be empty"))
        out.append(
            {
                "speaker": name or segment.speaker,
                "text": segment.text,
                "kind": segment.kind,
                "item_ids": segment.item_ids,
            }
        )
    if errors:
        raise FieldValidationError(errors)
    return out


async def update_episode(
    session: AsyncSession, user_id: uuid.UUID, episode_id: uuid.UUID, body: EpisodeUpdate
) -> Episode:
    """Edit a draft. Changing the script makes its audio out of date."""
    episode = await get_episode(session, user_id, episode_id)
    await _require_idle_draft(session, episode, "be edited")
    if body.title is not None:
        episode.title = body.title
    if body.description is not None:
        episode.description = body.description
    if body.segments is not None:
        script = dict(episode.script or {})
        names = await speaker_names(session, user_id, episode.show_id)
        segments = _checked_segments(body.segments, names)
        if segments != script.get("segments"):
            script["segments"] = segments
            script["revision"] = revision_of(episode.script) + 1
        episode.script = script  # a new dict, so the JSON column is seen as changed
    return await _save(session, episode)


async def resynthesize(session: AsyncSession, user_id: uuid.UUID, episode_id: uuid.UUID) -> Run:
    """Queue a run that voices and mixes the draft's current script again (not rewriting it).

    The caller starts the queued run's tasks. The episode moves to the new run, and the run that
    produced the draft is closed: its review is over.
    """
    episode = await get_episode(session, user_id, episode_id)
    await _require_idle_draft(session, episode, "be voiced again")
    if not segments_of(episode):
        raise EpisodeConflict("The episode has no script to voice")
    previous = episode.run_id
    try:
        run = await runs.create_run(session, user_id, episode.show_id, RunTrigger.RESYNTH)
    except runs.RunConflict as exc:
        raise EpisodeConflict(str(exc)) from exc
    episode.run_id = run.id
    if previous is not None:
        await session.execute(
            update(Run)
            .where(Run.id == previous, Run.status == RunStatus.AWAITING_REVIEW)
            .values(status=RunStatus.SUCCEEDED)
        )
    await add_event(session, run, "Voicing the edited script again", episode_id=str(episode.id))
    await session.commit()
    return run


async def _close_review(session: AsyncSession, episode: Episode, message: str) -> None:
    """The run that was waiting for this review is done."""
    if episode.run_id is None:
        return
    run = await session.get(Run, episode.run_id, populate_existing=True)
    if run is not None and run.status is RunStatus.AWAITING_REVIEW:
        run.status = RunStatus.SUCCEEDED
        await add_event(session, run, message, episode_id=str(episode.id))


async def approve(session: AsyncSession, user_id: uuid.UUID, episode_id: uuid.UUID) -> Episode:
    """Publish a draft. Its audio must have been voiced from the script as it is now."""
    episode = await get_episode(session, user_id, episode_id)
    await _require_idle_draft(session, episode, "be approved")
    if episode.audio_key is None:
        raise EpisodeConflict("The episode has no audio yet; re-synthesize it first")
    if not is_audio_current(episode):
        raise EpisodeConflict(
            "The script was edited after the audio was made; re-synthesize before approving"
        )
    episode.status = EpisodeStatus.PUBLISHED
    episode.published_at = datetime.now(UTC)
    await _close_review(session, episode, "Episode approved and published")
    return await _save(session, episode)


async def reject(
    session: AsyncSession, storage: Storage, user_id: uuid.UUID, episode_id: uuid.UUID
) -> Episode:
    """Throw a draft away: its stories become available again and its audio is deleted."""
    episode = await get_episode(session, user_id, episode_id)
    await _require_idle_draft(session, episode, "be rejected")
    if episode.audio_key is not None:
        await storage.delete(episode.audio_key)
    await session.execute(
        update(Item)
        .where(Item.used_in_episode_id == episode.id, Item.user_id == user_id)
        .values(used_in_episode_id=None)
    )
    episode.status = EpisodeStatus.REJECTED
    episode.audio_key = None
    episode.duration_s = None
    episode.size_bytes = None
    await _close_review(session, episode, "Episode rejected; its stories are available again")
    return await _save(session, episode)
