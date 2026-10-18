from datetime import UTC, datetime

from sqlalchemy import select

from byop.models import Episode
from byop.models.enums import EpisodeStatus, RunStatus, RunTrigger
from byop.pipeline.context import RunContext
from byop.pipeline.workdir import remove_work_dir
from byop.services.ranking import commit_items, release_items
from byop.services.usage import refresh_run_totals


async def run(ctx: RunContext) -> None:
    """End the run: publish the episode if the show publishes automatically, else leave it as a
    draft for review. The stories it used now belong to the episode."""
    await ctx.checkpoint()
    episode = await ctx.session.scalar(
        select(Episode).where(Episode.run_id == ctx.run.id, Episode.user_id == ctx.user_id)
    )
    if episode is not None:
        await commit_items(ctx.session, ctx.user_id, ctx.run.id, episode.id)
    else:  # nothing was written: give the stories back
        await release_items(ctx.session, ctx.user_id, ctx.run.id)
    await remove_work_dir(ctx.settings.media_root, ctx.run.id)

    now = datetime.now(UTC)
    publish = (
        episode is not None
        and ctx.show.auto_publish
        and ctx.run.trigger is not RunTrigger.RESYNTH  # a draft someone is reviewing stays theirs
        and episode.status is EpisodeStatus.DRAFT
        and episode.audio_key is not None
    )
    if publish and episode is not None:
        episode.status = EpisodeStatus.PUBLISHED
        episode.published_at = now
        ctx.run.status = RunStatus.SUCCEEDED
        message = "Run finished and the episode was published"
    elif episode is not None:
        ctx.run.status = RunStatus.AWAITING_REVIEW
        message = "Run finished: the episode is waiting for review"
    else:
        ctx.run.status = RunStatus.SUCCEEDED
        message = "Run finished"
    ctx.run.progress = 100
    ctx.run.finished_at = now
    await refresh_run_totals(ctx.session, ctx.run)
    await ctx.session.commit()
    await ctx.log(message, episode_id=str(episode.id) if episode else None)
