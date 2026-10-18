from datetime import UTC, datetime

from byop.models.enums import RunStatus
from byop.pipeline.context import RunContext
from byop.services.ranking import release_items


async def run(ctx: RunContext) -> None:
    """End the run. Stub: no episode is produced yet, so the reserved stories are given back.

    The real step creates the episode, calls `commit_items` for the stories it used and
    leaves the run `awaiting_review` (or `succeeded` when the show publishes automatically).
    """
    await ctx.checkpoint()
    await release_items(ctx.session, ctx.user_id, ctx.run.id)
    ctx.run.status = RunStatus.SUCCEEDED
    ctx.run.progress = 100
    ctx.run.finished_at = datetime.now(UTC)
    await ctx.session.commit()
    await ctx.log("Run finished (no episode is produced yet)")
