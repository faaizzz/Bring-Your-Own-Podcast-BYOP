import json
from pathlib import Path

import anyio
import structlog
from sqlalchemy import select

from byop.models import Episode
from byop.pipeline.context import RunContext
from byop.pipeline.errors import StageFailed, TransientStageError
from byop.pipeline.workdir import work_dir
from byop.services.audio_mix import ChunkRef, MixOptions, mix_episode
from byop.services.ffmpeg import FFmpegError
from byop.services.script_revision import revision_of
from byop.services.show_audio import key_of
from byop.storage import Storage, StorageError, build_storage, show_prefix

log = structlog.get_logger(__name__)

EPISODE_FILE = "episode.mp3"


def audio_key(show_id: object, episode_id: object) -> str:
    return f"{show_prefix(show_id)}/episodes/{episode_id}/audio.mp3"  # type: ignore[arg-type]


async def _fetch_asset(storage: Storage, key: str | None, target: Path) -> Path | None:
    """Copy a show's clip next to the work files, or None if the show has none (or it is gone)."""
    if not key:
        return None
    return target if await storage.get_file(key, target) else None


async def run(ctx: RunContext) -> None:
    """Mix the voiced chunks (and the show's clips and music bed, if any) into the episode MP3."""
    await ctx.checkpoint()
    base = work_dir(ctx.settings.media_root, ctx.run.id)
    manifest_path = anyio.Path(base / "manifest.json")
    if not await manifest_path.is_file():
        raise StageFailed("There is no voiced audio to mix.")
    manifest = json.loads(await manifest_path.read_text())

    episode = await ctx.session.scalar(
        select(Episode).where(Episode.run_id == ctx.run.id, Episode.user_id == ctx.user_id)
    )
    if episode is None:
        raise StageFailed("There is no episode to put the audio on.")
    segments = (episode.script or {}).get("segments")
    lines = segments if isinstance(segments, list) else []

    # The manifest lists chunks in script order, each with its files (several if a fallback with
    # a smaller limit voiced it in pieces).
    chunks = [
        ChunkRef(
            path=base / chunk["files"][i],
            segment=chunk["segment"],
            kind=chunk["kind"],
            item_ids=tuple(
                lines[chunk["segment"]].get("item_ids", []) if chunk["segment"] < len(lines) else []
            ),
        )
        for chunk in manifest["chunks"]
        for i in range(len(chunk["files"]))
    ]

    storage = build_storage(ctx.settings)
    assets = anyio.Path(base / "assets")
    await assets.mkdir(parents=True, exist_ok=True)
    try:
        intro = await _fetch_asset(storage, key_of(ctx.show, "intro"), base / "assets" / "intro")
        outro = await _fetch_asset(storage, key_of(ctx.show, "outro"), base / "assets" / "outro")
        music = await _fetch_asset(storage, key_of(ctx.show, "music"), base / "assets" / "music")
    except StorageError as exc:
        raise TransientStageError(f"Could not read the show's audio clips: {exc}") from exc

    settings = ctx.settings
    options = MixOptions(
        target_lufs=settings.audio_target_lufs,
        bitrate_kbps=settings.audio_bitrate_kbps,
        channels=settings.audio_channels,
        segment_gap_ms=settings.audio_segment_gap_ms,
        transition_gap_ms=settings.audio_transition_gap_ms,
        music_volume_db=settings.audio_music_volume_db,
    )

    async def progress(fraction: float) -> None:
        await ctx.progress(0.05 + 0.85 * fraction)

    await ctx.log(
        f"Mixing {len(chunks)} chunks"
        + (", with intro" if intro else "")
        + (", outro" if outro else "")
        + (" and a music bed" if music else "")
    )
    try:
        result = await mix_episode(
            chunks,
            base,
            base / EPISODE_FILE,
            options,
            intro=intro,
            outro=outro,
            music=music,
            checkpoint=ctx.checkpoint,
            progress=progress,
        )
    except FFmpegError as exc:
        raise StageFailed(f"Mixing the audio failed: {exc}") from exc

    key = audio_key(ctx.show.id, episode.id)
    try:
        await storage.put_file(key, result.path, content_type="audio/mpeg")
    except StorageError as exc:
        raise TransientStageError(f"Could not store the episode audio: {exc}") from exc
    episode.audio_key = key
    # The audio is of the script revision that was voiced, whatever the script says now.
    episode.script = {
        **(episode.script or {}),
        "audio_revision": manifest.get("script_revision", revision_of(episode.script)),
    }
    episode.duration_s = round(result.duration_s)
    episode.size_bytes = result.size_bytes
    await ctx.session.commit()
    await ctx.log(
        f"Episode audio ready: {result.duration_s / 60:.1f} minutes, "
        f"{result.size_bytes / 1_000_000:.1f} MB at {settings.audio_target_lufs:g} LUFS",
        duration_s=episode.duration_s,
        size_bytes=result.size_bytes,
        input_lufs=result.input_lufs,
        intro=intro is not None,
        outro=outro is not None,
        music=music is not None,
    )
    await ctx.progress(1.0)
