from datetime import UTC, datetime

from sqlalchemy import select

from byop.models import Episode
from byop.models.enums import RunStatus
from byop.pipeline.context import RunContext
from byop.services.ranking import commit_items, release_items


async def run(ctx: RunContext) -> None:
    """End the run. The stories it used now belong to its draft episode.

    Audio is not produced yet (a later step), so the run simply succeeds; the review step will
    make it wait for approval (or publish it) once there is something to listen to.
    """
    await ctx.checkpoint()
    episode_id = await ctx.session.scalar(
        select(Episode.id).where(Episode.run_id == ctx.run.id, Episode.user_id == ctx.user_id)
    )
    if episode_id is not None:
        await commit_items(ctx.session, ctx.user_id, ctx.run.id, episode_id)
    else:  # nothing was written: give the stories back
        await release_items(ctx.session, ctx.user_id, ctx.run.id)
    ctx.run.status = RunStatus.SUCCEEDED
    ctx.run.progress = 100
    ctx.run.finished_at = datetime.now(UTC)
    await ctx.session.commit()
    await ctx.log("Run finished", episode_id=str(episode_id) if episode_id else None)
