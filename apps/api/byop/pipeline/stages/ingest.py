from byop.models.enums import EventLevel
from byop.pipeline.context import RunContext
from byop.services.ingest.pipeline import ingest_show


async def run(ctx: RunContext) -> None:
    """Collect fresh items from the show's sources."""
    result = await ingest_show(
        ctx.session, ctx.resolver, ctx.settings, ctx.show.id, run_id=ctx.run.id
    )
    for report in result.sources:
        if report.error:
            await ctx.log(
                f"Source '{report.name}' failed: {report.error}",
                level=EventLevel.WARNING,
                source_id=str(report.source_id),
            )
    await ctx.log(
        f"Collected {result.new_items} new items from {len(result.sources)} sources",
        new_items=result.new_items,
        fetched=result.fetched,
        duplicates=result.duplicates,
        stale=result.stale,
    )
